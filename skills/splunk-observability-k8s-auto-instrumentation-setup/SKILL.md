---
name: splunk-observability-k8s-auto-instrumentation-setup
description: >-
  Render, apply, verify, and uninstall Splunk/OpenTelemetry Operator
  auto-instrumentation overlays for Kubernetes workloads after the base Splunk
  OTel Collector skill has installed the operator and CRDs. Emits language
  Instrumentation CRs, workload and namespace annotations, backup ConfigMaps,
  Splunk OBI eBPF assets, profiling/runtime metric env vars, sampler settings,
  Fargate gateway paths, vendor-coexistence checks, GitOps YAML, and clean
  uninstall scripts. Use when wiring zero-code Java, Node.js, Python, .NET, Go,
  Apache, Nginx, or SDK instrumentation into Splunk Observability Cloud APM,
  adding AlwaysOn Profiling, discovering workloads, or reverting
  operator-managed instrumentation.
---

# Splunk Observability Kubernetes Auto-Instrumentation

This skill configures operator-driven, zero-code application auto-instrumentation for Kubernetes workloads that send traces, metrics, and profiling to Splunk Observability Cloud.

It is an overlay on top of [splunk-observability-otel-collector-setup](../splunk-observability-otel-collector-setup/SKILL.md). That skill installs the Splunk OTel Collector chart, which in turn installs the OpenTelemetry Operator, the `Instrumentation` / `OpenTelemetryCollector` CRDs, and (optionally) a chart-managed default `Instrumentation` custom resource. This skill takes over from there: it renders one or more fully-configured `Instrumentation` custom resources per language, writes workload annotation patches that the operator mutating webhook reacts to, and drives the full lifecycle (apply, verify, uninstall).

## What it renders

- `k8s-instrumentation/instrumentation-cr.yaml` — one or more `Instrumentation` resources (multi-CR when the spec lists multiple).
- `k8s-instrumentation/workload-annotations.yaml` — strategic-merge patches against `spec.template.metadata.annotations` (NEVER top-level `metadata.annotations`) for each target `Deployment` / `StatefulSet` / `DaemonSet`.
- `k8s-instrumentation/namespace-annotations.yaml` — namespace-level `inject-<lang>` annotations for namespace-wide opt-in.
- `k8s-instrumentation/annotation-backup-configmap.yaml` — template ConfigMap that `apply-annotations.sh` populates with the pre-instrumentation state of each workload for clean revert.
- `k8s-instrumentation/obi-daemonset.yaml` — only when `--enable-obi`. Splunk OBI (eBPF) DaemonSet with namespace include/exclude selectors.
- `k8s-instrumentation/openshift-scc-obi.yaml` — only when `--distribution openshift` and `--enable-obi`. SCC binding for the OBI service account.
- `k8s-instrumentation/apply-instrumentation.sh` — CRD preflight, SCC then CR then DaemonSet apply, webhook readiness wait.
- `k8s-instrumentation/apply-annotations.sh` — resolve targets, snapshot backup, strategic-merge-patch, rollout restart per target.
- `k8s-instrumentation/uninstall.sh` — reverse patches from backup, rollout restart, delete CR (ordered before any chart removal).
- `k8s-instrumentation/verify-injection.sh` — deep check for specific workload (init container + env).
- `k8s-instrumentation/status.sh` — one-shot snapshot of CRs, MutatingWebhookConfiguration, operator pod.
- `k8s-instrumentation/list-instrumented.sh` — drift audit: annotated workloads vs pods actually carrying the init container.
- `k8s-instrumentation/preflight-report.md` — human-readable preflight verdict.
- `discovery/workloads.yaml` and `discovery/base-collector-probe.json` — only when `--discover-workloads`.
- `runbook.md` — ordered operator workflow from render through verify and optional uninstall.
- `handoff-collector.sh` — guidance to run `splunk-observability-otel-collector-setup` first if CRDs are absent.
- `handoff-native-ops.spec.yaml` — starter APM detectors spec for `splunk-observability-native-ops`.
- `handoff-dashboard-builder.spec.yaml` — APM topology dashboard spec for `splunk-observability-dashboard-builder`.
- `metadata.json` — spec digest, preflight verdicts, warning list, rendered file list, target workload list (consumed by `--target-all` on apply/uninstall).

## Safety Rules

- Never ask for a Splunk Observability access token or any other credential in conversation. This skill does not take or store tokens directly; the OpenTelemetry Operator resolves the ingest endpoint through the `$(SPLUNK_OTEL_AGENT)` env var injected by the base chart, and the chart already carries the ingest token in a Kubernetes Secret.
- Reject direct token flags such as `--access-token`, `--token`, `--bearer-token`, `--api-token`, `--o11y-token`, `--sf-token`, `--hec-token`, `--platform-hec-token`, `--api-key`. Any token file handling delegates to the base collector skill via the rendered `handoff-collector.sh`.
- Image-pull secrets for private registries mirroring `ghcr.io/signalfx/*` are passed by **name** (`--image-pull-secret <name>`); the operator creates the Kubernetes Secret itself and this skill never touches that material.
- Mutating operations are gated: `--apply-annotations` and `--uninstall-instrumentation` require `--accept-auto-instrumentation` (because both force pod restarts). `--apply-instrumentation` with `--enable-obi` requires `--accept-obi-privileged`.
- All rendered scripts are idempotent and refuse to run when expected preconditions (helm release present, CRDs installed, backup ConfigMap populated) are not met.

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
     --apply-instrumentation
   ```

6. Apply annotations + rollout restart:

   ```bash
   bash skills/splunk-observability-k8s-auto-instrumentation-setup/scripts/setup.sh \
     --apply-annotations \
     --accept-auto-instrumentation \
     --target-all
   ```

7. Verify injection:

   ```bash
   bash skills/splunk-observability-k8s-auto-instrumentation-setup/scripts/validate.sh \
     --live --check-injection
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

## OBI Behavior

`--enable-obi` emits a Splunk OpenTelemetry Zero-code (OBI) DaemonSet with `privileged: true`, `hostPath` mounts for `/sys/kernel/security` and `/sys/fs/cgroup`, and a kernel-≥5.8 requirement. OBI is eBPF-based and instruments compiled binaries (Go, C, Rust) without code or annotation changes. Apply requires `--accept-obi-privileged`. On OpenShift, `openshift-scc-obi.yaml` renders automatically to bind the `privileged` SCC to the OBI ServiceAccount.

See [references/obi-ebpf.md](references/obi-ebpf.md).

## Multi-CR / Multi-Environment

When the spec lists more than one `Instrumentation` CR (e.g. different samplers for dev vs prod), `--multi-instrumentation` MUST be passed. The operator chart turns on the corresponding feature gate. Each workload annotation then binds to a specific CR via `cr=<ns>/<crname>`. The preflight catalog refuses to render multiple CRs without the feature gate.

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

With `--live`:

- `--check-webhook` — operator MutatingWebhookConfiguration presence + webhook error log scan.
- `--check-instrumentation` — `kubectl get otelinst -A` shows the rendered CRs with expected fields.
- `--check-injection` — iterate annotated workloads, assert each has a Pod carrying the `opentelemetry-auto-instrumentation` init container and the expected `OTEL_*` env.
- `--check-apm <service>` — optional probe of `api.<realm>.signalfx.com/v2/apm/topology` for the workload's `service.name`.
- `--check-backup` — annotation backup ConfigMap exists and is non-empty.

See [reference.md](reference.md) for the full CLI flag reference and the thirteen `references/*.md` annexes for deep topical documentation.
