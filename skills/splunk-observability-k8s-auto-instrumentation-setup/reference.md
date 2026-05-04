# Splunk Observability Kubernetes Auto-Instrumentation Reference

## Source Guidance

This skill follows the `splunk-otel-collector` Helm chart documentation for the `operator`, `operatorcrds`, `certmanager`, `instrumentation`, and `obi` value blocks, the OpenTelemetry Operator documentation for the `Instrumentation` CRD, and the Splunk Observability Cloud documentation for per-language SDK images, `SPLUNK_PROFILER_*` / `SPLUNK_METRICS_*` env wiring, and AlwaysOn Profiling.

## Rendered Layout

By default, assets are written under `splunk-observability-k8s-auto-instrumentation-rendered/`.

```
splunk-observability-k8s-auto-instrumentation-rendered/
  k8s-instrumentation/
    instrumentation-cr.yaml
    obi-daemonset.yaml                   # only when --enable-obi
    openshift-scc-obi.yaml               # only when --distribution openshift AND --enable-obi
    namespace-annotations.yaml
    workload-annotations.yaml
    annotation-backup-configmap.yaml
    preflight-report.md
    apply-instrumentation.sh             # skipped in --gitops-mode
    apply-annotations.sh                  # skipped in --gitops-mode
    verify-injection.sh
    uninstall.sh                          # skipped in --gitops-mode
    status.sh
    list-instrumented.sh
  discovery/
    workloads.yaml                       # only when --discover-workloads
    base-collector-probe.json            # only when --discover-workloads
  runbook.md
  handoff-collector.sh
  handoff-native-ops.spec.yaml
  handoff-dashboard-builder.spec.yaml
  metadata.json
```

## Setup Modes

`setup.sh` is mode-driven:

- `--render` (default): write overlay assets; no cluster mutation.
- `--discover-workloads`: read-only `kubectl` walk + base-collector presence probe; writes starter `workloads.yaml` inventory.
- `--apply-instrumentation`: `kubectl apply -f instrumentation-cr.yaml` (+ OBI, + SCC for OpenShift).
- `--apply-annotations`: backup ConfigMap + strategic-merge-patch + rollout restart (gated by `--accept-auto-instrumentation`).
- `--uninstall-instrumentation`: reverse patches from backup + rollout restart + ordered CR delete (gated by `--accept-auto-instrumentation`).
- `--dry-run`: preview without writing files or touching the cluster; composable with all modes.
- `--json`: JSON dry-run shape for programmatic consumers.
- `--explain`: human-friendly plan summary.
- `--gitops-mode`: emit only self-contained YAML; skip imperative apply / uninstall scripts.

## Required Values

Always required for `--render`:

- `--realm` (Splunk Observability realm such as `us0`).
- `--cluster-name` unless `--distribution` is `eks`, `eks/auto-mode`, `gke`, `gke/autopilot`, or `openshift` (those auto-detect).
- `--deployment-environment` (prod / staging / dev — lands on every trace as the `deployment.environment` resource attribute).

## Full Flag Reference

### Identity

- `--realm`, `--cluster-name`, `--deployment-environment`
- `--namespace` (default `splunk-otel` — the namespace the Instrumentation CR lives in; must be reachable by annotated workloads, usually the base collector release namespace)
- `--instrumentation-cr-name` (default `splunk-otel-auto-instrumentation`; repeatable via spec for multi-CR)
- `--distribution` one of `eks | eks/auto-mode | eks/fargate | gke | gke/autopilot | openshift | aks | generic`
- `--base-release` (default `splunk-otel-collector`)
- `--base-namespace` (default `splunk-otel`)

### Languages and CR Configuration

- `--languages java,nodejs,python,dotnet,go,apache-httpd,nginx,sdk` (any subset; `sdk` is a language-agnostic env-only injection for apps that bundle their own OTel SDK)
- `--java-image`, `--nodejs-image`, `--python-image`, `--dotnet-image`, `--go-image`, `--apache-httpd-image`, `--nginx-image` — override the default `ghcr.io/signalfx/splunk-otel-*` image per language
- `--extra-env <lang>=KEY=VALUE` (repeatable)
- `--resource-limits <lang>=cpu=500m,memory=128Mi`
- `--image-pull-secret <secret-name>` for private/air-gapped registries

### Profiling and Runtime Metrics

- `--profiling-enabled` (AlwaysOn Profiling; sets `SPLUNK_PROFILER_ENABLED=true`)
- `--profiling-memory-enabled` (`SPLUNK_PROFILER_MEMORY_ENABLED=true`)
- `--profiler-call-stack-interval-ms <ms>`
- `--runtime-metrics-enabled` (Java + Node.js only; sets `SPLUNK_METRICS_ENABLED=true` and `SPLUNK_METRICS_ENDPOINT=http://$(SPLUNK_OTEL_AGENT):9943/v2/datapoint`)

### Trace Configuration

- `--propagators tracecontext,baggage,b3[,b3multi,jaeger,xray,ottrace,none]`
- `--sampler {always_on,always_off,traceidratio,parentbased_always_on,parentbased_always_off,parentbased_traceidratio,jaeger_remote,xray}`
- `--sampler-argument <value>`

### Endpoint

- `--agent-endpoint` (default `http://$(SPLUNK_OTEL_AGENT):4317`)
- `--gateway-endpoint <url>` (required for `--distribution eks/fargate` and any gateway-only topology)
- `--per-language-endpoint java=http://...:4318` (HTTP OTLP override; repeatable)

### Resource Attributes

- `--use-labels-for-resource-attributes` (enables `defaults.useLabelsForResourceAttributes: true`)
- `--multi-instrumentation` (operator feature gate; required when rendering >1 language CR)
- `--extra-resource-attr service.namespace=payments` (repeatable)

### Operator Tuning

- `--operator-watch-namespaces ns1,ns2` (empty = cluster-scoped)
- `--webhook-cert-mode {auto,cert-manager,external}`
- `--installation-job-enabled` (default true — required on Helm v4)

### OBI

- `--enable-obi`
- `--obi-namespaces ns1,ns2` (default: empty; empty means cluster-scoped observation)
- `--obi-exclude-namespaces kube-system,kube-public`
- `--obi-version <version>`
- `--accept-obi-privileged` (required for `--apply-instrumentation` with `--enable-obi`)
- `--render-openshift-scc` (auto-on when `--distribution openshift && --enable-obi`; set to `false` to refuse)

### Annotations

- `--annotate-namespace <ns>=<lang[,lang...]>` (repeatable)
- `--annotate-workload <Kind>/<ns>/<name>=<lang>[,container-names=a,b][,dotnet-runtime=linux-x64|linux-musl-x64][,go-target-exe=/path][,cr=<ns>/<crname>][,disable=true]` (repeatable)
- `--inventory-file workloads.yaml`

### Target Filtering

- `--target <Kind>/<ns>/<name>` (repeatable) — apply/uninstall only the matching workloads
- `--target-all` — apply/uninstall all workloads recorded in `metadata.json`
- `--purge-crs` — uninstall path: also delete every rendered Instrumentation CR after annotations are restored

### Vendor Coexistence

- `--detect-vendors` — scan for Datadog / New Relic / AppDynamics / Dynatrace mutating webhooks
- `--exclude-vendor datadog,newrelic` — emit exclusion env snippet for documented vendor agents

### Apply Gates

- `--accept-auto-instrumentation` (required for `--apply-annotations` and `--uninstall-instrumentation`)
- `--accept-obi-privileged` (required for `--apply-instrumentation` with `--enable-obi`)
- `--kube-context <name>` (propagated to all `kubectl` / `helm` invocations in rendered scripts)

### Backup / Restore

- `--backup-configmap <name>` (default `splunk-otel-auto-instrumentation-annotations-backup`)
- `--restore-from-backup`
- `--purge-backup` (delete backup ConfigMap after a successful uninstall)

## CR Name Precedence

When multiple Instrumentation CRs are rendered and a workload annotation does not include `cr=<ns>/<crname>`, the default CR is the first entry in the spec `instrumentationCRs` list (or the one named by `--instrumentation-cr-name`). The preflight catalog reports every workload that resolved to the default so the operator can verify.

## Preflight Catalog

### Fail-render

- Missing `--cluster-name` when distribution is not in the auto-detect set.
- `--distribution eks/fargate` without `--gateway-endpoint`.
- `--languages go` with any Go-annotated workload missing `go-target-exe=<path>`.
- `--languages dotnet` with Windows-targeted node pools or `dotnet-runtime=windows-*` (`.NET Framework` is explicitly refused).
- Multiple language CRs rendered without `--multi-instrumentation`.
- `--apply-annotations` without `--accept-auto-instrumentation`.
- `--apply-instrumentation` with `--enable-obi` but without `--accept-obi-privileged`.
- Rendered `workload-annotations.yaml` would patch top-level `metadata.annotations` (guard against the most common authoring bug).
- `--apply-instrumentation` when the base collector helm release is absent.
- `--distribution openshift && --enable-obi` with `--render-openshift-scc=false`.
- `--target`/`--target-all` for apply/uninstall but `metadata.json` from a prior render is missing.
- Spec lists a workload in a PSS `restricted` / `baseline` namespace while Go or OBI instrumentation is requested for it.

### Warn

- `--languages dotnet` with arm64 node selectors (Splunk .NET is x86/AMD64 only).
- `--profiling-enabled` with explicit JDK 8 < 8u262 or Oracle JDK 8 / IBM J9 (profiling unsupported).
- Cilium on EKS without ENI mode (port 9443 webhook risk).
- GKE Private Cluster distribution (firewall rule on 9443 required).
- OpenShift without `--distribution openshift` (SCC not applied).
- Helm v4 with `installationJob.enabled=false`.
- Alpine/musl nodes with `--languages python`.
- Third-party APM vendor webhook detected.
- Istio `istio-injection=enabled` on target namespace without `container-names=` on the workload annotation.
- Target workload already has `JAVA_TOOL_OPTIONS`, `NODE_OPTIONS`, `PYTHONPATH`, `CORECLR_PROFILER`, or `OTEL_*` env set.
- `--base-namespace` does not match the CR namespace.
- Target workload in `metadata.json` has been deleted from the cluster since the last render.

### Advisory

- Instrumentation CR image / env changes require pod restart; annotated workloads should be rolled out after updates.
- `kubectl rollout restart` is idempotent.

## Apply / Uninstall Ordering

See [references/annotation-surgery.md](references/annotation-surgery.md) for the exact patch mechanics.

`apply-instrumentation.sh`:

1. Assert `kubectl get crd instrumentations.opentelemetry.io` succeeds.
2. On OpenShift + OBI, apply `openshift-scc-obi.yaml` first.
3. `kubectl apply -f instrumentation-cr.yaml` (+ `obi-daemonset.yaml`).
4. Wait for the operator webhook endpoint on port 9443.

`apply-annotations.sh`:

1. Resolve the target set from `--target`, `--target-all`, or `metadata.json`.
2. Skip workloads already at the desired state.
3. For each non-skipped target: if the backup key is absent, write the current `spec.template.metadata.annotations` into the backup ConfigMap.
4. Apply strategic-merge patch to `spec.template.metadata.annotations` only.
5. `kubectl rollout restart` each changed workload sequentially.
6. Print applied / skipped / failed summary.

`uninstall.sh`:

1. Resolve the target set.
2. For each target, reverse the patch from the backup key. If the key is missing, strip only the `inject-*` annotations (best-effort revert).
3. `kubectl rollout restart` each affected workload.
4. If `--purge-crs` or all annotated workloads are now clean: `kubectl delete otelinst <name> -n <ns>` for each rendered CR (BEFORE any `helm uninstall` to avoid an orphan).
5. Keep the backup ConfigMap for 7 days (TTL label) unless `--purge-backup`.

## Validation

`validate.sh` is static by default. The `--live` probes are:

- `--check-webhook` — MutatingWebhookConfiguration presence and clean operator logs.
- `--check-instrumentation` — `kubectl get otelinst -A` matches the rendered CRs.
- `--check-injection` — sample pods carry the `opentelemetry-auto-instrumentation` init container and expected `OTEL_*` env.
- `--check-apm <service>` — probe `api.<realm>.signalfx.com/v2/apm/topology` for the workload's `service.name`.
- `--check-backup` — backup ConfigMap exists and is non-empty.

See the thirteen topical `references/*.md` annexes for more:

- [instrumentation-cr-reference.md](references/instrumentation-cr-reference.md)
- [annotation-catalog.md](references/annotation-catalog.md)
- [profiling-and-runtime-metrics.md](references/profiling-and-runtime-metrics.md)
- [distribution-preflights.md](references/distribution-preflights.md)
- [pss-and-sidecars.md](references/pss-and-sidecars.md)
- [vendor-coexistence.md](references/vendor-coexistence.md)
- [obi-ebpf.md](references/obi-ebpf.md)
- [annotation-surgery.md](references/annotation-surgery.md)
- [endpoint-selection.md](references/endpoint-selection.md)
- [troubleshooting.md](references/troubleshooting.md)
- [migration-guide.md](references/migration-guide.md)
- [discovery-workflow.md](references/discovery-workflow.md)
- [gitops-mode.md](references/gitops-mode.md)
