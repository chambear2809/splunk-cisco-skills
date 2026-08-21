---
name: splunk-observability-k8s-auto-instrumentation-setup
description: "Use when wiring zero-code Java, Node.js, Python, .NET, Go, Apache, or Nginx instrumentation into Splunk
  Observability Cloud APM, adding AlwaysOn Profiling, discovering workloads, or reverting operator-managed
  instrumentation. Render, apply, verify, and uninstall Splunk/OpenTelemetry Operator auto-instrumentation
  overlays for Kubernetes workloads after the base Splunk OTel Collector skill has installed the operator
  and CRDs. Emits language Instrumentation CRs, workload and namespace annotations, backup ConfigMaps,
  Splunk OBI eBPF assets, profiling/runtime metric env vars, sampler settings, Fargate gateway paths,
  GitOps YAML, transactional rollback snapshots, and clean uninstall scripts."
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-08-20"
---

# Splunk Observability Kubernetes Auto-Instrumentation

## Prerequisites

| Tool or access | Purpose | Verify |
|---|---|---|
| Bash and Python 3 | Run bundled setup and validation helpers | `bash --version && python3 --version` |
| Required product/platform access | Inspect or configure the selected target | Complete the documented preflight |
| Credential files for live modes | Keep secrets out of chat | Verify paths only |

## Workflow Overview

```text
┌───────────┐   ┌───────────────┐   ┌───────────────┐   ┌─────────────────┐
│ Preflight │ → │ Render/review │ → │ Apply/handoff │ → │ Validate evidence │
└───────────┘   └───────────────┘   └───────────────┘   └─────────────────┘
```

## When to Activate

- Wiring zero-code Java, Node.js, Python, .NET, Go, Apache, or Nginx instrumentation into Splunk Observability Cloud
  APM, adding AlwaysOn Profiling, discovering workloads, or reverting operator-managed instrumentation.
- Preview and review the splunk observability k8s auto instrumentation setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/splunk-observability-k8s-auto-instrumentation-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/splunk-observability-k8s-auto-instrumentation-setup/scripts/validate.sh --help
```

Expected output: offline, live, and completion options are displayed when the
skill supports them; help exits without mutation.

## Troubleshooting

| Issue | Cause | Resolution |
|---|---|---|
| Preflight fails | A required tool or access path is missing | Resolve it before rendering or applying |
| Rendered assets are incomplete | Required non-secret inputs are absent | Complete intake and render again |
| Apply is blocked | Review, credentials, or explicit acceptance is missing | Use the documented handoff |
| Validation is incomplete | Live evidence is unavailable | Record the gap and keep completion open |

This skill configures operator-driven, zero-code application auto-instrumentation for Kubernetes workloads that send traces, metrics, and profiling to Splunk Observability Cloud.

It is an overlay on top of [splunk-observability-otel-collector-setup](../splunk-observability-otel-collector-setup/SKILL.md). That skill installs the Splunk OTel Collector chart, which in turn installs the OpenTelemetry Operator, the `Instrumentation` / `OpenTelemetryCollector` CRDs, and (optionally) a chart-managed default `Instrumentation` custom resource. This skill takes over from there: it renders one or more fully-configured `Instrumentation` custom resources per language, writes workload annotation patches that the operator mutating webhook reacts to, and drives the full lifecycle (apply, verify, uninstall).

## What it renders

- `k8s-instrumentation/instrumentation-cr.yaml` — one or more `Instrumentation` resources (multi-CR when the spec lists multiple).
- `k8s-instrumentation/workload-annotations.yaml` — strategic-merge patches against `spec.template.metadata.annotations` (NEVER top-level `metadata.annotations`) for each target `Deployment` / `StatefulSet` / `DaemonSet`.
- `k8s-instrumentation/namespace-annotations.yaml` — namespace-level `inject-<lang>` annotations for namespace-wide opt-in.
- `k8s-instrumentation/annotation-backup-configmap.yaml` — owned template ConfigMap for versioned, managed-key-only rollback snapshots.
- `k8s-instrumentation/annotation-backup.py` — reviewed transactional capture/verify/restore planner; it fails before workload mutation on kubectl, JSON, ownership, or completeness errors.
- `k8s-instrumentation/obi-daemonset.yaml` — only when `--enable-obi`. Owned ServiceAccount plus digest-pinned Splunk OBI (eBPF) DaemonSet with namespace include/exclude selectors.
- `k8s-instrumentation/obi-lifecycle.py` — exact OBI ownership/config, rollout, node/kernel coverage, bounded-log validation, and safe purge helper.
- `k8s-instrumentation/managed-resource-lifecycle.py` — preflights every rendered Instrumentation/OBI/SCC identity before the first mutation, rejects foreign same-name objects, and uses UID/resourceVersion-bound replace/delete operations.
- `k8s-instrumentation/openshift-scc-obi.yaml` — only when `--distribution openshift` and `--enable-obi`. SCC binding for the OBI service account.
- `k8s-instrumentation/apply-instrumentation.sh` — CRD preflight, SCC then CR then DaemonSet apply, webhook readiness wait.
- `k8s-instrumentation/apply-annotations.sh` — resolve and merge multi-language targets, transactionally snapshot every managed key, verify the committed backup, then strategic-merge-patch and restart.
- `k8s-instrumentation/uninstall.sh` — refuse missing/corrupt/incomplete snapshots, restore only rendered managed keys, restart, and optionally purge owned OBI resources and CRs.
- `k8s-instrumentation/injection-audit.py` — standalone fail-closed audit engine shared by rendered diagnostics.
- `k8s-instrumentation/verify-injection.sh` — deep check for one or all rendered workloads (exact managed annotations, CR binding, init/sidecar evidence, OTLP env, and language hook).
- `k8s-instrumentation/status.sh` — one-shot snapshot of CRs, MutatingWebhookConfiguration, operator pod.
- `k8s-instrumentation/list-instrumented.sh` — runs the same deep drift audit for every rendered target before printing the inventory.
- `k8s-instrumentation/preflight-report.md` — human-readable preflight verdict.
- `discovery/workloads.yaml` and `discovery/base-collector-probe.json` — only when `--discover-workloads`.
- `runbook.md` — ordered operator workflow from render through verify and optional uninstall.
- `handoff-collector.sh` — guidance to run `splunk-observability-otel-collector-setup` first if CRDs are absent.
- `handoff-native-ops.spec.yaml` — starter APM detectors spec for `splunk-observability-native-ops`.
- `handoff-dashboard-builder.spec.yaml` — APM topology dashboard spec for `splunk-observability-dashboard-builder`.
- `metadata.json` — spec digest, preflight verdicts, warning list, rendered file list, target workload list, and namespace-level injection contracts. Workload targets are consumed by `--target-all` on apply/uninstall; workload and namespace targets are consumed by the deep live auditor.

## Safety Rules

- Never ask for a Splunk Observability access token or any other credential in conversation. This skill does not accept credentials on argv or render them. The OpenTelemetry Operator resolves ingest through the `$(SPLUNK_OTEL_AGENT)` env var injected by the base chart. The optional APM API validation reads a separate mode-0600 User API access-token file through `SPLUNK_O11Y_TOKEN_FILE`; an ingest-only Org token is not sufficient for that read API.
- Reject direct token flags such as `--access-token`, `--token`, `--bearer-token`, `--api-token`, `--o11y-token`, `--sf-token`, `--hec-token`, `--platform-hec-token`, `--api-key`. Ingest-token handling delegates to the base collector; the read-only APM probe accepts only the dedicated file path from `SPLUNK_O11Y_TOKEN_FILE`.
- Reject secret-like keys or values in specs, `--extra-env`, resource attributes, headers, and endpoints (`token`, `HEC`, `Bearer`, `Authorization`, password, API-key, or Secret material). OTLP URLs must be credential-free HTTP(S) URLs with an explicit port and no userinfo, query, or fragment.
- Image-pull secrets for private registries mirroring `ghcr.io/signalfx/*` are passed by **name** (`--image-pull-secret <name>`); the operator creates the Kubernetes Secret itself and this skill never touches that material.
- Mutating operations are gated: `--apply-instrumentation`, `--apply-annotations`, and `--uninstall-instrumentation` require `--accept-auto-instrumentation`; CR changes can affect already-annotated workloads on their next restart, while annotation apply/uninstall forces restarts immediately. `--apply-instrumentation` with `--enable-obi` also requires `--accept-obi-privileged`.
- Every live validation or mutation requires `--kube-context <name>`. Operators who intentionally use kubectl's current context must say so with `--allow-current-context`; the two flags are mutually exclusive. Non-mutating `--dry-run` previews do not require either acknowledgement.
- Cluster name is always explicit. This offline renderer never guesses an EKS/GKE/OpenShift identity.
- Operator installation controls (watch namespaces, certificate mode, installation job, or a purported multi-instrumentation feature gate) and vendor webhook detection are not implemented by this overlay. Supplying those legacy inputs fails closed; configure/audit them in the base collector workflow.
- Rendered mutations are repeatable and fail closed on missing preconditions (helm release, CRDs, or an owned complete backup). Annotation apply/uninstall intentionally triggers a new rollout on every invocation and is therefore operationally disruptive even when the annotation values are unchanged.
- Same-name Instrumentation, OBI ServiceAccount/DaemonSet, and OpenShift SCC objects are never adopted implicitly. Apply preflights the full set before its first write; existing objects must carry the exact skill ownership labels, and replacements/deletes are bound to the live UID and resourceVersion. Backup purge requires `--target-all`, exact snapshot-key coverage, and a UID/resourceVersion-bound ConfigMap delete.

## Primary Workflow

1. Confirm the base collector + operator are installed. If not, run [splunk-observability-otel-collector-setup](../splunk-observability-otel-collector-setup/SKILL.md) first. The rendered `handoff-collector.sh` carries the exact command.

2. (Optional) Discover candidate workloads. This is read-only; no cluster mutation:

   ```bash
   bash skills/splunk-observability-k8s-auto-instrumentation-setup/scripts/setup.sh \
     --discover-workloads \
     --realm us0 \
     --cluster-name prod-cluster
   ```

   Then edit `splunk-observability-k8s-auto-instrumentation-rendered/discovery/workloads.yaml` to mark each workload with its language.

3. Render the overlay assets:

   The CLI-only path is the default; `template.example` is loaded only when
   explicitly passed with `--spec`. This prevents example workloads or policy
   settings from contaminating an operator's CLI render.

   ```bash
   bash skills/splunk-observability-k8s-auto-instrumentation-setup/scripts/setup.sh \
     --render \
     --realm us0 \
     --cluster-name prod-cluster \
     --deployment-environment prod \
     --languages java,nodejs,python \
     --profiling-enabled \
     --runtime-metrics-enabled \
     --annotate-workload Deployment/prod/payments-api=java \
     --annotate-workload Deployment/prod/checkout-web=nodejs \
     --annotate-workload Deployment/prod/fraud-score=python
   ```

4. Review `splunk-observability-k8s-auto-instrumentation-rendered/`:
   - `preflight-report.md` — every fail / warn / advisory finding.
   - `runbook.md` — ordered operator steps.
   - `k8s-instrumentation/instrumentation-cr.yaml` — the CRs that will be applied.
   - `k8s-instrumentation/workload-annotations.yaml` — the strategic-merge patches.

5. Apply the Instrumentation CR(s) first:

   ```bash
   bash skills/splunk-observability-k8s-auto-instrumentation-setup/scripts/setup.sh \
     --apply-instrumentation \
     --accept-auto-instrumentation \
     --kube-context prod-cluster-admin
   ```

6. Apply annotations + rollout restart:

   ```bash
   bash skills/splunk-observability-k8s-auto-instrumentation-setup/scripts/setup.sh \
     --apply-annotations \
     --accept-auto-instrumentation \
     --kube-context prod-cluster-admin \
     --target-all
   ```

7. Verify injection:

   ```bash
   bash skills/splunk-observability-k8s-auto-instrumentation-setup/scripts/validate.sh \
     --check-injection \
     --kube-context prod-cluster-admin
   ```

## Annotation Model

The OpenTelemetry Operator reacts to pod annotations placed at `spec.template.metadata.annotations` on Deployment / StatefulSet / DaemonSet objects (or at the namespace level). This skill writes strategic-merge patches that target **only** `spec.template.metadata.annotations`; it never touches top-level `metadata.annotations`.

Supported annotations:

- `instrumentation.opentelemetry.io/inject-<lang>: "true"` — inject using the chart-default Instrumentation CR.
- `instrumentation.opentelemetry.io/inject-<lang>: "<namespace>/<crname>"` — inject using a specific CR (used for multi-CR / multi-env).
- `instrumentation.opentelemetry.io/inject-<lang>: "false"` — explicit opt-out for a specific pod.
- `instrumentation.opentelemetry.io/container-names: "app,sidecar"` — required in Istio-enabled namespaces to avoid instrumenting the `istio-proxy` sidecar.
- `instrumentation.opentelemetry.io/otel-dotnet-auto-runtime: linux-x64 | linux-musl-x64` — Alpine vs glibc for .NET.
- `instrumentation.opentelemetry.io/otel-go-auto-target-exe: /path/to/binary` — mandatory for Go (eBPF needs the target binary path).

See [references/annotation-catalog.md](references/annotation-catalog.md) for the full surface, [references/annotation-surgery.md](references/annotation-surgery.md) for the patching mechanics, and [references/instrumentation-cr-reference.md](references/instrumentation-cr-reference.md) for CR field semantics.

### Namespace-level live contract

For each rendered namespace target, live validation requires the Namespace's
managed annotations to match metadata exactly. Every non-terminating pod whose
phase is not `Succeeded` or `Failed` remains in scope and must be Running,
Ready, and carry the expected language evidence. A pod-level
`inject-<language>: "false"` is the only exclusion and is itself audited for
stale injection artifacts. A pod-level explicit CR value remains in scope and
is validated against that rendered CR. Terminal and deleting pods are reported
as excluded. A namespace with no active pods fails closed because it provides
no production evidence.

`namespace-annotations.yaml` is declarative input for GitOps or a separately
reviewed `kubectl apply`; the imperative `apply-annotations.sh` target selector
continues to mutate only explicitly rendered workloads.

## OBI Behavior

`--enable-obi` emits an owned ServiceAccount and Splunk OpenTelemetry Zero-code (OBI) DaemonSet with `privileged: true`, `hostPath` mounts for `/sys/kernel/security` and `/sys/fs/cgroup`, Linux-node selection, and a kernel-≥5.8 requirement. OBI is eBPF-based and instruments compiled binaries (Go, C, Rust) without code or annotation changes. Apply requires `--accept-obi-privileged`. Because this repository has no audited default for the standalone OBI container contract, render also requires `--obi-image ...@sha256:<digest>`; tag-only `--obi-version` input fails closed. On OpenShift, `openshift-scc-obi.yaml` renders automatically. `--check-obi` proves the exact digest/config, controller rollout, one Ready OBI pod on every supported Ready schedulable Linux node, and a bounded 10-minute/200-line fatal-rule log window. `uninstall.sh --purge-obi` verifies exact ownership/config before deleting DaemonSet, optional SCC, then ServiceAccount.

See [references/obi-ebpf.md](references/obi-ebpf.md).

## Multi-CR / Multi-Environment

When the spec lists more than one `Instrumentation` CR (e.g. different samplers for dev vs prod), each workload annotation binds to a specific CR via `cr=<ns>/<crname>`. The OpenTelemetry Operator supports distinct named resources; this overlay does not claim or mutate a separate chart feature gate. Multiple language rows for one workload are intentionally merged into one manifest; duplicate workload/language rows or conflicting shared annotations fail closed.

This skill always renders an explicit `<namespace>/<crname>` value, including
for the default CR, so cross-namespace workloads never depend on the ambiguous
bare `"true"` lookup. `--namespace` overrides every rendered CR namespace;
`--instrumentation-cr-name` is accepted only for a single-CR render.

## Instrumentation image policy

Java, Node.js, Python, .NET, Go, and Apache HTTPD defaults are immutable
`@sha256` pins copied from the base Collector skill's chart-0.158.0 audited
image ledger. Custom image overrides must also be digest-pinned. This
repository has no audited Nginx default image, so Nginx fails closed until the
operator supplies a reviewed `--nginx-image ...@sha256:<digest>` override.

## Hand-offs

- Base collector + operator + CRDs: [splunk-observability-otel-collector-setup](../splunk-observability-otel-collector-setup/SKILL.md). Run first.
- Starter APM detectors: [splunk-observability-native-ops](../splunk-observability-native-ops/SKILL.md). Consume `handoff-native-ops.spec.yaml`.
- APM topology dashboards: [splunk-observability-dashboard-builder](../splunk-observability-dashboard-builder/SKILL.md). Consume `handoff-dashboard-builder.spec.yaml`.

## Out of scope

- Installing the base collector, operator, CRDs, or cert-manager (handled by the base collector skill).
- Linux / systemd / preload instrumentation (handled by the base collector skill).
- HEC token creation for Splunk Platform logs (handled by [splunk-hec-service-setup](../splunk-hec-service-setup/SKILL.md)).
- Application-side SDK wiring (manual instrumentation). This skill is zero-code-only.
- .NET Framework (Windows) auto-instrumentation — not supported by Splunk; explicitly refused.
- Modifying application container images or Dockerfiles; all injection is via the operator init container pattern.
- Splunk On-Call routing and PagerDuty handoff (see [splunk-oncall-setup](../splunk-oncall-setup/SKILL.md) and [splunk-observability-native-ops](../splunk-observability-native-ops/SKILL.md)).

## Validation

```bash
bash skills/splunk-observability-k8s-auto-instrumentation-setup/scripts/validate.sh
```

Static checks cover:

- YAML well-formedness of every rendered manifest.
- `workload-annotations.yaml` patches target `spec.template.metadata.annotations` (not top-level `metadata.annotations`).
- Go workloads include `otel-go-auto-target-exe=`.
- No `.NET Framework` references anywhere.
- Rendered scripts do not echo secrets.
- CR name uniqueness.
- Every Instrumentation language image is pinned by `@sha256` and the JSON
  injection contract exactly matches `instrumentation-cr.yaml`.
- The rendered backup and OBI helpers byte-match their reviewed source; the OBI
  metadata contract exactly matches the rendered ServiceAccount/DaemonSet/SCC.

`--live --check-apm <service>` runs the complete production gate. It enables
webhook, Instrumentation CR, injection, backup, optional OBI, and scoped APM checks. A caller
may explicitly omit only the APM or backup gate with `--skip-apm-check` or
`--skip-backup-check`; those named skips are valid only with `--live`. Individual
`--check-*` flags remain available as narrow diagnostics.

- `--check-webhook` — exact pinned pod-admission webhook policy/route, CA bundle,
  Service and ready 9443/TCP EndpointSlice (with a legacy Endpoints fallback
  only when EndpointSlice is unavailable or empty), Ready Operator pods, and recent webhook
  error log scan. This proves Kubernetes routing state but does not synthesize
  an admission request or perform a separate TLS handshake.
- `--check-instrumentation` — `kubectl get otelinst -A` shows the rendered CRs with expected fields.
- `--check-injection` — iterate annotated workloads and namespace contracts. Workload controllers must have observed their current generation and completed rollout; all intended active pods must be Running and Ready with exact language injection evidence, the exact rendered `@sha256` init/sidecar image, and expected `OTEL_*` env. Namespace opt-outs and terminal/deleting exclusions follow the contract above.
- `--check-obi` — prove the owned OBI manifest contract, digest/config identity, DaemonSet rollout, supported kernel/architecture coverage, Ready pods, and bounded fatal-rule recent logs.
- `--check-apm <service>` — allow only a service/realm pair bound to a rendered workload in `metadata.json`, then probe the scoped topology for that service, deployment environment, and Kubernetes cluster.
- `--check-backup` — every rendered workload has a versioned, owned, structurally complete managed-key snapshot.

Every requested live check is fail-closed: a missing tool, credential,
resource, injected pod, backup, API response, or exact APM service is a
validation failure. The composed AWS/EKS/O11y staging gate is documented in
[`../../scripts/staging/README.md`](../../scripts/staging/README.md).

See [reference.md](reference.md) for the full CLI flag reference and the thirteen `references/*.md` annexes for deep topical documentation.
