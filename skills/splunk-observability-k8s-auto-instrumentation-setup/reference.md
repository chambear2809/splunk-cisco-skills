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
    annotation-backup.py                  # transactional capture/verify/restore planner
    preflight-report.md
    apply-instrumentation.sh             # skipped in --gitops-mode
    apply-annotations.sh                  # skipped in --gitops-mode
    injection-audit.py                    # standalone fail-closed live audit engine
    obi-lifecycle.py                      # OBI ownership/health/purge engine
    managed-resource-lifecycle.py         # ownership + UID/RV-safe apply/delete engine
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

`setup.sh` does not load a spec implicitly. A CLI-only render starts from safe,
empty defaults; `template.example` participates only when the operator passes
`--spec` explicitly. The shipped template contains no workload or namespace
targets. Apply and uninstall modes with no new render inputs reuse the existing
packet at `--output-dir`; they fail before cluster access when that packet is
missing. Passing any render input intentionally produces a fresh packet first.

## Required Values

Always required for `--render`:

- `--realm` (Splunk Observability realm such as `us0`).
- `--cluster-name` (always explicit; the offline renderer does not auto-detect it).
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

- `--languages java,nodejs,python,dotnet,go,apache-httpd,nginx` (any subset)
- `--java-image`, `--nodejs-image`, `--python-image`, `--dotnet-image`, `--go-image`, `--apache-httpd-image`, `--nginx-image` — override a language image; every override must use `@sha256:<64 hex>`. Java, Node.js, Python, .NET, Go, and Apache have repository-audited defaults; Nginx requires an explicit reviewed digest.
- `--extra-env <lang>=KEY=VALUE` (repeatable; secret-like keys/values and OTLP authorization headers are rejected)
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

- `--agent-endpoint` (default `http://$(SPLUNK_OTEL_AGENT):4317`; endpoints must be credential-free HTTP(S) URLs with explicit ports and no userinfo/query/fragment)
- `--gateway-endpoint <url>` (required for `--distribution eks/fargate` and any gateway-only topology)
- `--per-language-endpoint java=http://...:4318` (HTTP OTLP override; repeatable)

### Resource Attributes

- `--use-labels-for-resource-attributes` (enables `defaults.useLabelsForResourceAttributes: true`)
- `--extra-resource-attr service.namespace=payments` (repeatable)

Operator watch scope, webhook certificates, and installation-job values belong
to the base collector chart workflow. Legacy attempts to pass those controls to
this overlay fail closed rather than pretending the values were applied.

### OBI

- `--enable-obi`
- `--obi-namespaces ns1,ns2` (default: empty; empty means cluster-scoped observation)
- `--obi-exclude-namespaces kube-system,kube-public`
- `--obi-image <uri@sha256:digest>` (required with `--enable-obi`; no audited default)
- `--obi-version <version>` (legacy tag-only input; rejected)
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
- `--purge-obi` — uninstall path: verify exact OBI ownership/config, then delete DaemonSet, optional SCC, and ServiceAccount

Vendor coexistence remains a documented manual audit. This offline overlay does
not scan vendor webhooks or mutate vendor agent settings; legacy vendor-control
inputs fail closed.

### Apply Gates

- `--accept-auto-instrumentation` (required for every live `--apply-instrumentation`, `--apply-annotations`, and `--uninstall-instrumentation` operation)
- `--accept-obi-privileged` (required for `--apply-instrumentation` with `--enable-obi`)
- `--kube-context <name>` (propagated to all `kubectl` / `helm` invocations in rendered scripts)
- `--allow-current-context` (explicit alternative when intentionally using kubectl's current context; conflicts with `--kube-context`)

### Backup / Restore

- `--backup-configmap <name>` (default `splunk-otel-auto-instrumentation-annotations-backup`)
- `--purge-backup` (after a successful uninstall, delete only when `--target-all`
  covers every exact snapshot key; deletion is bound to the verified live
  ConfigMap UID/resourceVersion)

## CR Name Precedence

When multiple Instrumentation CRs are rendered and a workload annotation does not include `cr=<ns>/<crname>`, the default CR is the first entry in the spec `instrumentationCRs` list. The renderer writes that CR's explicit `<namespace>/<name>` into every default-bound annotation; it never emits a bare `"true"` for a generated target. `--namespace` overrides every rendered CR namespace. `--instrumentation-cr-name` is intentionally rejected for multi-CR specs because one CLI name cannot unambiguously rename a list.

## Namespace Audit Semantics

`metadata.json.namespace_targets` is the canonical live contract for
`namespace-annotations.yaml`. Duplicate rows for one namespace are merged into
one deterministic language/annotation record.

- The live Namespace must have exactly the rendered managed annotations.
- Intended active pods are all pods without `deletionTimestamp` whose phase is
  neither `Succeeded` nor `Failed`. Pending or otherwise unready pods stay in
  scope and fail the Ready gate.
- A pod-level `inject-<language>: "false"` is the only exclusion from that
  namespace language. The auditor also proves that no language-specific init
  container, sidecar, hook environment, or mount remains.
- A pod-level explicit CR override is not an exclusion; it must resolve to a
  rendered CR and pass the same language evidence checks.
- Terminal and deleting pods are counted and reported but excluded from
  injection evidence.
- Zero active pods is a hard failure, including namespaces containing only
  completed or deleting pods.

`verify-injection.sh --target Namespace/<name>` audits one namespace contract;
`--target-all`, `list-instrumented.sh`, and `validate.sh --check-injection`
audit workload and namespace contracts together.

## Preflight Catalog

### Fail-render

- Missing explicit `--cluster-name` for any distribution.
- Unsupported realm; invalid DNS-1123 namespace/CR/resource identity; malformed or credential-bearing OTLP URL; duplicate/incompatible propagators; unsupported sampler or invalid ratio.
- Secret-like spec, extra-env, header, endpoint, or resource-attribute keys/values.
- `--distribution eks/fargate` without `--gateway-endpoint`.
- `--languages go` with any Go-annotated workload missing `go-target-exe=<path>`.
- `--languages dotnet` with Windows-targeted node pools or `dotnet-runtime=windows-*` (`.NET Framework` is explicitly refused).
- Duplicate workload/language rows or conflicting shared annotations on intentional multi-language workload rows.
- Operator-installation or vendor controls supplied to this overlay.
- Any mutable or tag-only Instrumentation image; Nginx without an explicit audited digest.
- A workload binding that names a missing CR or a CR without the target language.
- `--instrumentation-cr-name` with a multi-CR spec.
- `--apply-annotations` without `--accept-auto-instrumentation`.
- Live `--apply-instrumentation` without `--accept-auto-instrumentation`.
- Any live apply/uninstall without `--kube-context`, unless `--allow-current-context` is explicit.
- `--apply-instrumentation` with `--enable-obi` but without `--accept-obi-privileged`.
- Rendered `workload-annotations.yaml` would patch top-level `metadata.annotations` (guard against the most common authoring bug).
- `--apply-instrumentation` when the base collector helm release is absent.
- `--distribution openshift && --enable-obi` with `--render-openshift-scc=false`.
- `--enable-obi` without an explicit reviewed digest-pinned `--obi-image`, or with legacy `--obi-version`.
- `--target`/`--target-all` for apply/uninstall but `metadata.json` from a prior render is missing.
- Spec lists a workload in a PSS `restricted` / `baseline` namespace while Go or OBI instrumentation is requested for it.

### Warn

- `--languages dotnet` with arm64 node selectors (Splunk .NET is x86/AMD64 only).
- `--profiling-enabled` with explicit JDK 8 < 8u262 or Oracle JDK 8 / IBM J9 (profiling unsupported).
- Cilium on EKS without ENI mode (port 9443 webhook risk).
- GKE Private Cluster distribution (firewall rule on 9443 required).
- OpenShift without `--distribution openshift` (SCC not applied).
- Alpine/musl nodes with `--languages python`.
- Istio `istio-injection=enabled` on target namespace without `container-names=` on the workload annotation.
- Target workload already has `JAVA_TOOL_OPTIONS`, `NODE_OPTIONS`, `PYTHONPATH`, `CORECLR_PROFILER`, or `OTEL_*` env set.
- `--base-namespace` does not match the CR namespace.
- Target workload in `metadata.json` has been deleted from the cluster since the last render.

### Advisory

- Instrumentation CR image / env changes require pod restart; annotated workloads should be rolled out after updates.
- Re-running annotation apply/uninstall intentionally creates another rollout; review it as a disruptive repeat operation, not a no-op.

## Apply / Uninstall Ordering

See [references/annotation-surgery.md](references/annotation-surgery.md) for the exact patch mechanics.

`apply-instrumentation.sh`:

1. Assert the explicit context/current-context acknowledgement and `kubectl get crd instrumentations.opentelemetry.io` succeed.
2. On OpenShift + OBI, apply `openshift-scc-obi.yaml` first.
3. `kubectl apply -f instrumentation-cr.yaml` (+ `obi-daemonset.yaml`).
4. Fail closed unless the exact Operator webhook Service becomes ready on
   9443/TCP, preferring EndpointSlice and using the same guarded legacy
   Endpoints fallback as validation.

`apply-annotations.sh`:

1. Resolve the target set from `--target`, `--target-all`, or `metadata.json`.
2. Merge intentional multi-language rows by workload; reject duplicate languages or conflicting shared keys.
3. Read and validate every selected workload before mutation. Capture only the managed annotation keys into versioned snapshots; create/replace the owned ConfigMap using `resourceVersion`, re-read it, and verify every snapshot.
4. Abort before the first workload patch on any kubectl, JSON, identity, ownership, collision, or snapshot validation error.
5. Apply one strategic-merge patch per workload to `spec.template.metadata.annotations` only, then restart and wait sequentially.

`uninstall.sh`:

1. Resolve the target set.
2. Validate every selected workload plus every owned, versioned snapshot before emitting the first patch. Missing, corrupt, incomplete, wrong-owner, or wrong-target backups are hard failures.
3. Restore only the exact managed-key union for that workload. Previously present values are restored; previously absent keys are nulled; unrelated annotations are never included.
4. `kubectl rollout restart` each affected workload.
5. `--purge-obi` validates ownership/config before ordered DaemonSet/SCC/ServiceAccount deletion. `--purge-crs` remains explicit and ordered before any base-chart removal.
6. Keep the backup ConfigMap for 7 days (TTL label) unless `--purge-backup`.

## Validation

`validate.sh` is static by default. `--live --check-apm <service>` is the
complete production gate. It enables all probes below; only
`--skip-apm-check` and `--skip-backup-check` may explicitly omit their named
gates. Individual `--check-*` flags run narrow diagnostics. Every live or
narrow live check requires `--kube-context CTX`, or the explicit
`--allow-current-context` acknowledgement when the current context is
intentional.

- `--check-webhook` — exact pinned pod webhook policy/client/rule, injected CA
  bundle, Service-to-ready-9443/TCP EndpointSlice route (falling back to core
  Endpoints only when the EndpointSlice API is unavailable or returns no
  matching slices), Ready Operator pods, and
  clean recent Operator logs. It does not issue a synthetic admission request
  or perform a separate TLS handshake.
- `--check-instrumentation` — `kubectl get otelinst -A` matches the rendered CRs.
- `--check-injection` — every rendered controller has observed its current generation and completed its kind-specific rollout; every selected workload pod and intended active namespace pod is Running and Ready, resolves the expected CR, and carries the exact digest-pinned language init/sidecar image, OTLP endpoint, and runtime hook. Namespace bindings, explicit opt-outs, and exclusions follow the contract above. The rendered `verify-injection.sh` and `list-instrumented.sh` use the same reviewed fail-closed auditor. Static validation rejects a rendered auditor whose bytes differ from the skill source.
- `--check-obi` — when OBI is enabled, compare the owned live ServiceAccount/DaemonSet/optional SCC to the rendered metadata contract, prove a fully observed/Ready rollout, validate every Ready schedulable Linux node against the ≥5.8 kernel and supported-architecture contract, prove one exact-image Ready pod per eligible node, and scan at most 200 lines from the last 10 minutes per pod under a 1-MiB aggregate cap for defined fatal rules.
- `--check-apm <service>` — require an exact service/realm binding from `metadata.json.apm_services`, then probe the scoped topology for that service, environment, and cluster.

The APM topology read requires `SPLUNK_O11Y_REALM` and a mode-0600
`SPLUNK_O11Y_TOKEN_FILE` containing a User API access token with permission to
read APM topology. The base Collector's ingest-only Org token is not an API-read
credential and is not reused by this validator.
- `--check-backup` — every workload has an owned, versioned, complete managed-key snapshot.

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
