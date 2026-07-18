---
name: cisco-isovalent-platform-setup
description: "Use when installing or validating Cilium, Tetragon, Hubble, or Isovalent platform workflows on
  Kubernetes. Install and operate Cisco Isovalent on Kubernetes: Cilium, Tetragon, Enterprise add-ons, and
  gated private Isovalent product packs. Renders OSS or Enterprise Helm assets, distribution and CNI-
  conflict preflights, feature coverage, apply plans, doctor reports, live validation, and day-2
  discover/backup/upgrade/rollback/uninstall runbooks. NOT a Splunk TA skill; Splunk telemetry wiring is
  delegated to splunk-observability-isovalent-integration."
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-07-02"
---

# Cisco Isovalent Platform Setup

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

- Installing or validating Cilium, Tetragon, Hubble, or Isovalent platform workflows on Kubernetes.
- Preview and review the cisco isovalent platform setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/cisco-isovalent-platform-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/cisco-isovalent-platform-setup/scripts/validate.sh --help
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

This skill installs the **Isovalent platform itself** on a Kubernetes cluster. It is **NOT** a Splunk Platform TA installer (the `-platform-setup` suffix disambiguates from `cisco-*-setup` skills like `cisco-meraki-ta-setup` or `cisco-intersight-setup`, which install Splunk-side add-ons).

For the Splunk Observability Cloud + Splunk Platform integration with this stack, use [splunk-observability-isovalent-integration](../splunk-observability-isovalent-integration/SKILL.md). For the Splunk Platform Cisco Security Cloud App that ingests Tetragon process-exec events into the `cisco_isovalent` index, use [cisco-security-cloud-setup](../cisco-security-cloud-setup/SKILL.md) with `PRODUCT=isovalent`.

## Edition split

- **OSS (default, `--edition oss`)**:
  - `helm repo add cilium https://helm.cilium.io`
  - Charts: `cilium/cilium`, `cilium/tetragon`
  - No license, public.
- **Enterprise (`--edition enterprise`)**:
  - `helm repo add isovalent https://helm.isovalent.com`
  - Charts: `isovalent/cilium-enterprise`, `isovalent/tetragon` (Enterprise variant), `isovalent/cilium-dnsproxy`, `isovalent/hubble-enterprise` (private chart — "contact the Splunk + Isovalent team"), `isovalent/hubble-timescape`.
  - Mutating Enterprise apply paths require `--isovalent-license-file`; optionally `--isovalent-pull-secret-file` for the private registry.
- **EKS-AWS mirror**: `oci://public.ecr.aws/eks/cilium/cilium` for EKS Hybrid Nodes (set `--eks-mirror`).

## Feature Catalog and Coverage

Every Cisco Isovalent target product feature is tracked in `catalog.json` and every render writes:

- `feature-catalog.json`
- `feature-matrix.md`
- `coverage-report.json`
- `environment-profiles.json`
- `environment-profiles.md`
- `apply-plan.json`
- `doctor-report.md`

Each feature has exactly one status: `helm_apply`, `kubectl_apply`, `cli_apply`, `live_validate`, `discover_only`, `delegated_handoff`, `gated_private`, `not_applicable`, or `unsupported_with_reason`. Gated private rows such as Hubble Enterprise, Hubble Timescape, and Isovalent Load Balancer include an explicit chart/customer-doc access workflow instead of being omitted.

## Environment Profiles

Set `distribution` in the spec or pass `--distribution`. Supported profiles are:

`generic`, `kubeadm`, `kind`, `minikube`, `kops`, `eks`, `eks-byocni`, `eks-hybrid`, `aks-byocni`, `aks-managed-cilium`, `gke`, `gke-dataplane-v2`, `openshift`, `rke2`, `rancher`, `k3s`, `k0s`, `talos`, `vmware-vsphere`, and `alibaba-ack`.

Each profile records preflight checks, install path, cloud-CNI conflicts, kube-proxy handling, IPAM constraints, required privileges, SCC/PSA/RBAC needs, kernel/eBPF requirements, LB/IPAM limitations, and not-applicable features. `distribution: openshift` renders `k8s/openshift-scc.yaml`.

## Step-granular apply

`--apply <step>[,<step>...]` accepts: `cilium`, `tetragon`, `hubble`, `dnsproxy`, `timescape`, `load-balancer`, `network-policy`, `gateway-api`, `ingress`, `service-mesh`, `clustermesh`, `egress-gateway`, `bgp`, `lb-ipam`, `l2-announcements`, `encryption`, `host-firewall`, and `runtime-policies`. Legacy aliases such as `hubble-enterprise` are accepted. With no list, applies the standard subset (`cilium,tetragon`).

`--apply --dry-run` runs non-mutating Helm/Kubectl dry-run validation where supported.

Scoped Cilium feature sections render their own values overlays under `helm/cilium-section-<section>-values.yaml` and apply those overlays rather than rerunning the base Cilium values unchanged. `clustermesh` is handled through the Cilium CLI because it is a multi-cluster wiring operation, not a single Helm values toggle.

## Preflights

- **Kernel >= 5.10** for Cilium v1.18.x; not supported on Ubuntu 20.04 or RHEL 8 (per AWS EKS Hybrid Nodes docs).
- **EKS BYOCNI**: Cilium on EKS requires the cluster created with `--network-plugin none`. Renderer emits a preflight warning + `eksctl` example.
- **CNI conflict**: Cilium fails if the AWS VPC CNI is still installed. Renderer warns.

All namespace fields must be Kubernetes DNS-1123 labels. The kernel minimum
must be numeric `major.minor` or `major.minor.patch`; both contracts are
validated before executable assets are rendered.

## Audited chart versions

- Cilium OSS: `1.18.10`; Cilium Enterprise: `1.18.8`; EKS OCI mirror: separately classified `1.18.8`.
- Tetragon OSS: `1.7.0`; Tetragon Enterprise: `1.18.1`.
- Cilium DNSProxy, Hubble Enterprise, and Hubble Timescape: `1.18.8`.

Generated Helm scripts verify and install the exact version with atomic,
wait/timeout-bound transactions. `metadata.json` and `apply-plan.json` record
the complete chart contract. The repository does not contain independently
audited chart archives, signatures, or checksums, and private Hubble chart
origin remains entitlement-dependent; this provenance gap is recorded
explicitly rather than represented by an invented digest.

When an Enterprise license file is supplied to a Helm dry-run, the generated
script first proves that `helm upgrade --hide-secret` is supported and adds the
flag. It fails before rendering if that capability is unavailable.

## Tetragon export defaults

Tetragon Helm values default to:

```yaml
export:
  mode: file
  exportDirectory: /var/run/cilium/tetragon
  exportFilename: tetragon.log
  exportFilePerm: "644"
```

This is the **production-validated path** that coordinates with `splunk-observability-isovalent-integration`'s `agent.extraVolumes` hostPath mount and `logsCollection.extraFileLogs.filelog/tetragon` block. Override with `--export-mode stdout|fluentd` for users whose SCC/PSP policies block hostPath mounts (`stdout`) or who insist on the legacy fluentd `splunk_hec` output (`fluentd` — flagged DEPRECATED, the upstream `fluent-plugin-splunk-hec` was archived 2025-06-24).

## Safety Rules

- Never ask for the Isovalent license key in conversation; never inline it.
- Use `--isovalent-license-file` (chmod 600 enforced) only.
- Use `--isovalent-pull-secret-file` (chmod 600 enforced) for the registry pull secret only.
- Reject direct license/secret flags (`--license`, `--license-key`, `--pull-secret`).
- Live commands require `--kube-context CTX` unless `--allow-current-context` is explicitly passed.
- Mutating `--apply` requires `--accept-k8s-apply`.
- Dataplane/security-disruptive sections require `--accept-isovalent-disruptive-change`.
- Enterprise license and pull-secret material is consumed by file path only. Generated commands use `--set-file` or Kubernetes Secret file input after chart values are verified; they never echo secret values or use `$(cat secret)` in argv.
- Hubble Enterprise and Hubble Timescape charts are **private** by default. Without `--private-chart-access-verified`, their scripts fail closed with the Splunk + Isovalent access runbook. With `--private-chart-access-verified`, the renderer marks those features `helm_apply`, verifies chart values with `helm show values`, and emits live Helm apply commands.

## Primary Workflow

1. Choose edition and namespace layout.

2. Render:

   ```bash
   bash skills/cisco-isovalent-platform-setup/scripts/setup.sh \
     --render \
     --edition oss \
     --distribution generic \
     --output-dir cisco-isovalent-platform-rendered
   ```

3. Review `cisco-isovalent-platform-rendered/`:
   - `helm/cilium-values.yaml`
   - `helm/tetragon-values.yaml`
   - `helm/tracing-policy.yaml` (starter)
   - `helm/cilium-dnsproxy-values.yaml` (Enterprise only, when --enable-dnsproxy)
   - `helm/hubble-timescape-values.yaml` (Enterprise only, when --enable-timescape)
   - `helm/hubble-enterprise-values.yaml` (Enterprise only, when --enable-hubble-enterprise; private chart gated unless access is verified)
   - `scripts/install-cilium.sh`, `install-tetragon.sh`, `install-cilium-dnsproxy.sh` (Ent), `install-hubble-enterprise.sh` (Ent), `install-hubble-timescape.sh` (Ent)
   - `scripts/preflight.sh` (kernel + CNI conflict + EKS BYOCNI checks)
   - `scripts/eksctl-byocni-example.sh`
   - `feature-matrix.md`, `coverage-report.json`, `apply-plan.json`, `doctor-report.md`, `environment-profiles.*`
   - `metadata.json`

4. Apply only when explicitly requested:

   ```bash
   bash skills/cisco-isovalent-platform-setup/scripts/setup.sh \
     --apply cilium,tetragon \
     --edition oss \
     --kube-context prod-use1 \
     --accept-k8s-apply \
     --accept-isovalent-disruptive-change
   ```

   For Enterprise:

   ```bash
   bash skills/cisco-isovalent-platform-setup/scripts/setup.sh \
     --apply cilium,tetragon,hubble,dnsproxy \
     --edition enterprise \
     --kube-context prod-use1 \
     --isovalent-license-file /tmp/isovalent_license \
     --isovalent-pull-secret-file /tmp/isovalent_pull_secret \
     --private-chart-access-verified \
     --accept-k8s-apply \
     --accept-isovalent-disruptive-change
   ```

## Day-2 Operations

- `--discover`: read-only Helm/CRD/node/CLI inventory.
- `--preflight`: read-only kernel, CNI-conflict, distribution, and chart-access checks.
- `--doctor`: render the feature/catalog troubleshooting report.
- `--validate --live`: read-only Helm status and service metrics probes.
- `--backup`: read-only Helm values/history backup.
- `--upgrade-plan`: render a release/version/values-hash review.
- `--rollback-plan`: render Helm rollback guidance with CNI continuity warnings.
- `--uninstall-plan`: render an uninstall runbook. The skill does not silently uninstall the active CNI.
- Splunk telemetry wiring remains delegated to `splunk-observability-isovalent-integration`.

## Validation

```bash
bash skills/cisco-isovalent-platform-setup/scripts/validate.sh
```

Static checks confirm rendered values and catalog reports exist. With `--live --kube-context CTX`:

- Fail-closed Helm inventory and a fresh structured `helm status` read for required Cilium and Tetragon releases. The status document is streamed into a strict deployed-state parser and never retained or echoed, because release NOTES can contain customer data. Inventory uses explicit deployed/failed/pending/uninstalling/superseded/uninstalled flags common to Helm 3 and Helm 4; it does not use Helm 3-only `helm list --all`. Duplicate same-name releases across namespaces, an unexpected release namespace, a wrong chart identity, exact-version drift, or a post-inventory status transition fails validation. Enterprise add-on releases are required only when enabled in the rendered metadata; an absent disabled add-on remains optional.
- Ready-pod checks for the Cilium and Tetragon agents on Helm-owned/BYOCNI profiles. Enabled Hubble Enterprise uses its exact Helm-instance label; Cilium DNSProxy uses the chart's real `k8s-app=cilium-dnsproxy` label. Each requires at least one pod and all matched pods/containers Ready in its own rendered add-on namespace.
- On Helm-owned/BYOCNI profiles, Kubernetes service API-proxy metric probes for Cilium 9962, Hubble 9965, Cilium Envoy 9964, and Cilium operator 9963. Tetragon 2112 and Tetragon operator 2113 are probed on every supported profile. Cilium DNSProxy 9967 is required only when that add-on is enabled. A no-pipe parser recognizes Prometheus/OpenMetrics numeric, timestamp, and exemplar syntax without `pipefail`/SIGPIPE false failures on large responses. Unreachable or sample-free required endpoints fail validation. Wherever a required Cilium/DNSProxy response exposes `cilium_hive_status`, any positive `status="degraded"` or `status="failed"` sample fails with a controlled metric/rule/count summary; `stopped` does not fail without source-backed unhealthy semantics.
- Tetragon pod-log checks through the Kubernetes pod log API use a bounded 20-line tail per agent pod. Panic, fatal, runtime-error, and export-failure patterns fail validation; diagnostics include rule identifiers only and never echo matched log content. Validation does not execute commands inside pods, directly request Kubernetes Secret payloads, or retrieve installed Helm values that could contain license material. File/stdout/fluentd export structure is validated statically from the rendered Tetragon values; fluentd requires the complete `splunk_hec` directive set and retains a placeholder token only.
- Hubble Timescape discovery supports both a standalone `hubble-timescape` Helm release and a Timescape StatefulSet bundled into the `cilium` Helm release. Acceptance requires observed generation convergence, desired/current/updated/ready replica equality, and matching current/update revisions; `readyReplicas` alone is insufficient.
- Live validation rejects kubectl clients outside the supported +/-1 minor skew from the Kubernetes API server. Static validation recursively parses rendered YAML/JSON and rejects inline license/token/password/API-key/private-key material without printing values.

Live validation aggregates all required failures and exits nonzero if any are present. It does not create debug pods or otherwise mutate the cluster.

`aks-managed-cilium` and `gke-dataplane-v2` are provider-owned dataplanes whose internal pod labels and metric Service names are not a stable interface owned by this skill. Live validation skips the Helm-specific Cilium pod/service probes, continues validating Tetragon, records an explicit unsupported-evidence failure, and exits nonzero so the result cannot be mistaken for complete production acceptance. A provider-approved dataplane evidence packet is required separately.

See `reference.md` for option details and the `references/` annexes for OSS-vs-Enterprise charts, EKS BYOCNI, kernel prerequisites, TracingPolicy cookbook, Tetragon export modes, and troubleshooting.
