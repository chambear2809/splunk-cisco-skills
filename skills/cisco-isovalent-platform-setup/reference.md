# Cisco Isovalent Platform Setup Reference

## Source guidance

- Cilium OSS Helm chart: `helm.cilium.io` — chart `cilium/cilium`.
- Tetragon OSS Helm chart: `helm.cilium.io` — chart `cilium/tetragon` (per `tetragon.cilium.io/docs/reference/helm-chart/`).
- Isovalent Enterprise Helm repo: `helm.isovalent.com` — charts `isovalent/cilium-enterprise`, `isovalent/tetragon`, `isovalent/cilium-dnsproxy`, `isovalent/hubble-enterprise` (private), `isovalent/hubble-timescape`.
- AWS EKS Hybrid Nodes Cilium build (mirror): `oci://public.ecr.aws/eks/cilium/cilium`.
- Cisco Isovalent acquisition: completed 2024-04-12 (per `investor.cisco.com/news/news-details/2024/...`).

## Audited chart contract

| Release | Chart | Exact version |
|---|---|---:|
| OSS Cilium | `cilium/cilium` | `1.18.10` |
| Enterprise Cilium | `isovalent/cilium-enterprise` | `1.18.8` |
| EKS OCI Cilium mirror | `oci://public.ecr.aws/eks/cilium/cilium` | `1.18.8` |
| OSS Tetragon | `cilium/tetragon` | `1.7.0` |
| Enterprise Tetragon | `isovalent/tetragon` | `1.18.1` |
| Cilium DNSProxy | `isovalent/cilium-dnsproxy` | `1.18.8` |
| Hubble Enterprise | `isovalent/hubble-enterprise` | `1.18.8` |
| Hubble Timescape | `isovalent/hubble-timescape` | `1.18.8` |

Every generated Helm command runs `helm show chart --version`, then uses the
same exact `--version` with `--atomic --wait --timeout 10m --history-max 10`.
Live validation requires the matching Chart.yaml identity and exact version.
The versions and accepted identities are recorded under `helm_charts` in both
`metadata.json` and `apply-plan.json`.

Provenance limitation: this repository does not redistribute the upstream
chart archives, `.prov` signatures, or independently audited SHA-256 values.
The private Hubble charts additionally require entitled repository access.
Consequently, exact version resolution is fail-closed, but origin/archive
integrity remains an explicit review gap rather than a fabricated checksum.

OSS and Enterprise pins are intentionally separate. Upstream Cilium `1.18.10`
is the current 1.18 maintenance baseline; the skill does not reuse the
cluster-validated Enterprise `1.18.8` pin for public GKE installs because that
upstream version has a documented GKE regression. Enterprise and EKS-mirror
versions remain separate evidence contracts rather than inferred upgrades.

## Rendered layout

By default, assets are written under `cisco-isovalent-platform-rendered/`:

- `helm/cilium-values.yaml`
- `helm/tetragon-values.yaml`
- `helm/tracing-policy.yaml` (when enabled)
- `helm/cilium-dnsproxy-values.yaml` (Enterprise + `--enable-dnsproxy`)
- `helm/hubble-enterprise-values.yaml` (Enterprise + `--enable-hubble-enterprise`; private chart)
- `helm/hubble-timescape-values.yaml` (Enterprise + `--enable-timescape`)
- `scripts/install-cilium.sh`
- `scripts/install-tetragon.sh`
- `scripts/install-cilium-dnsproxy.sh`
- `scripts/install-hubble-enterprise.sh` (fails closed with the access runbook unless private chart access is verified)
- `scripts/install-hubble-timescape.sh` (fails closed with the access runbook unless private chart access is verified)
- `scripts/preflight.sh` (kernel + EKS BYOCNI + CNI conflict checks)
- `scripts/eksctl-byocni-example.sh` (when requested)
- `feature-catalog.json`
- `feature-matrix.md`
- `coverage-report.json`
- `environment-profiles.json`
- `environment-profiles.md`
- `apply-plan.json`
- `doctor-report.md`
- `k8s/openshift-scc.yaml` (when `distribution: openshift`)
- `metadata.json`

## Setup modes

- `--render` — render Helm values + install scripts (default).
- `--discover` — read-only live inventory of Helm releases, CRDs, nodes, and CLI availability.
- `--preflight` — render then run read-only Kubernetes preflights.
- `--doctor` — render `doctor-report.md`.
- `--apply [STEPS]` — render then apply selected install steps. Steps: `cilium, tetragon, hubble, dnsproxy, timescape, load-balancer, network-policy, gateway-api, ingress, service-mesh, clustermesh, egress-gateway, bgp, lb-ipam, l2-announcements, encryption, host-firewall, runtime-policies`. With no list, applies `cilium,tetragon`.
- `--backup` — read-only Helm values/history backup.
- `--upgrade-plan` — render `upgrade-plan.md`.
- `--rollback-plan` — render `rollback-plan.md`.
- `--uninstall-plan` — render `uninstall-plan.md`.
- `--feature-matrix` — render and report the feature matrix and coverage report.
- `--validate` — run static validation against an already-rendered output.
- `--live` — with `--validate`, run read-only live probes.
- `--dry-run` — show the plan without writing. With `--apply`, run Helm/Kubectl dry-run validation where supported.
- `--json` — emit JSON dry-run output.
- `--explain` — print plan in plain English.

Live commands require `--kube-context CTX` unless `--allow-current-context` is explicitly set. Mutating `--apply` requires `--accept-k8s-apply`; disruptive dataplane/security sections also require `--accept-isovalent-disruptive-change`.

Enterprise Helm dry-runs that receive a license file require
`helm upgrade --hide-secret`; generated scripts capability-check the flag and
stop before rendering when it is unavailable. Live Helm status documents are
streamed into a deployed-state parser so NOTES are neither retained nor echoed.

Namespace intake is restricted to Kubernetes DNS-1123 labels, and the kernel
minimum accepts only numeric `major.minor` or `major.minor.patch`. These values
are emitted through validated shell variables rather than interpolated command
text. Static validation recursively parses rendered YAML/JSON and rejects
inline license/token/password/key material without printing the value.

Scoped Cilium sections render dedicated overlays under `helm/cilium-section-<section>-values.yaml` so an apply request changes the requested feature instead of replaying the base chart values. `clustermesh` is intentionally CLI-backed (`cilium clustermesh ...`) because it depends on participating cluster contexts.

## Edition flags

- `--edition oss` — default; uses `cilium/cilium` and `cilium/tetragon` from `helm.cilium.io`.
- `--edition enterprise` — uses `isovalent/*` from `helm.isovalent.com`. Mutating Enterprise apply steps require `--isovalent-license-file`. Optional `--isovalent-pull-secret-file` for the private registry.
- `--private-chart-access-verified` — assert that the operator has working private Isovalent chart access. This changes Hubble Enterprise and Hubble Timescape from fail-closed gated runbooks to Helm apply scripts that first run `helm show values`.
- `--eks-mirror` — use `oci://public.ecr.aws/eks/cilium/cilium` instead of the public OSS repo (EKS Hybrid Nodes).

## Distribution profiles

Supported `--distribution` values are `generic`, `kubeadm`, `kind`, `minikube`, `kops`, `eks`, `eks-byocni`, `eks-hybrid`, `aks-byocni`, `aks-managed-cilium`, `gke`, `gke-dataplane-v2`, `openshift`, `rke2`, `rancher`, `k3s`, `k0s`, `talos`, `vmware-vsphere`, and `alibaba-ack`.

Each profile defines preflight checks, install path, CNI conflicts, kube-proxy handling, IPAM constraints, required privileges, SCC/PSA/RBAC requirements, kernel/eBPF requirements, LB/IPAM limitations, and not-applicable features. The OpenShift profile renders SCC assets instead of relying on stale cross-skill claims.

For `aks-managed-cilium` and `gke-dataplane-v2`, `--validate --live` does not assume the Helm chart's `k8s-app=cilium` pod label or Cilium/Hubble metric Service names. Those provider-owned internals are not a stable contract of this skill. The validator skips those probes, validates the Tetragon portion, emits an explicit unsupported-evidence failure, and returns nonzero until provider-approved dataplane evidence is supplied separately.

All other live runs reject kubectl clients outside the supported one-minor
skew from the API server. Enabled Hubble Enterprise and Cilium DNSProxy releases
must be in their rendered namespaces and every release-labeled pod must be
Running with all declared containers Ready; DNSProxy must also expose samples
on its required metrics endpoint.

Helm inventory uses explicit status flags supported by Helm 3 and Helm 4, not
`helm list --all`. Metrics are parsed in-process from the captured response so
large bodies cannot false-fail through `grep -q`/`pipefail` SIGPIPE behavior.
For required Cilium and enabled DNSProxy responses, positive
`cilium_hive_status` samples with status `degraded` or `failed` fail closed.
Output reports only the metric name, rule identifier, and aggregate positive
count; label content is not echoed. Positive `stopped` is recorded as ordinary
sample evidence and is not treated as unhealthy without documented semantics.

## Tetragon export modes

`--export-mode` (or `tetragon.export.mode` in the spec):

- `file` (default): writes to `/var/run/cilium/tetragon/tetragon.log`. Coordinates with `splunk-observability-isovalent-integration`'s `agent.extraVolumes` hostPath mount and `logsCollection.extraFileLogs.filelog/tetragon` block.
- `stdout`: Tetragon prints events to container stdout. Picked up by the OTel collector's container log collection. Use when SCC/PSP policies block hostPath mounts.
- `fluentd`: **DEPRECATED.** Renders the legacy `fluent-plugin-splunk-hec` block. The plugin was archived 2025-06-24; plan to migrate to `file` mode.

## Preflights

- **Kernel >= 5.10**: required for Cilium v1.18.x. Renderer emits a per-node check.
- **EKS BYOCNI**: Cilium on EKS requires the cluster created with `--network-plugin none`. Renderer warns if `aws-node` DaemonSet is found.
- **CNI conflict**: Cilium fails if AWS VPC CNI is still installed. Same check as EKS BYOCNI.

Use `--render-eksctl-example` to also render an `eksctl` BYOCNI example for greenfield clusters.

## Secret handling

- `--isovalent-license-file` (chmod 600 enforced) for mutating Enterprise apply steps.
- `--isovalent-pull-secret-file` (chmod 600 enforced) for the Isovalent private registry pull secret (Docker config JSON).
- Generated Enterprise commands use file-path-only handoff (`--set-file` and Kubernetes Secret file input). They never pass raw secret values or command substitutions like `$(cat secret)` in argv.

Rejected direct flags: `--license`, `--license-key`, `--pull-secret`. Each error message points at the matching `--*-file` flag.

## Hubble Enterprise (private chart)

The Hubble Enterprise chart is **not publicly distributed**. The Splunking Isovalent blog (2026-02-02) explicitly says: "For information on accessing the Helm repository, contact the Splunk + Isovalent team directly via the following link: https://isovalent.com/splunk-contact-us/".

Without `--private-chart-access-verified`, `scripts/install-hubble-enterprise.sh` and `scripts/install-hubble-timescape.sh` print these instructions and exit non-zero. The values files are still rendered locally for review. With `--private-chart-access-verified`, the scripts add/update the Isovalent repo, run `helm show values` against the private chart, and then use Helm upgrade/install with the rendered values.

## Cross-skill coordination

- Splunk Observability Cloud + Splunk Platform integration -> `splunk-observability-isovalent-integration`. The Tetragon `export.mode: file` default coordinates with that skill's hostPath mount + extraFileLogs block.
- Splunk Platform Cisco Security Cloud App for Tetragon process-exec events -> `cisco-security-cloud-setup` with `PRODUCT=isovalent`.

Deep-dive annexes (all under `references/`):

- `references/oss-vs-enterprise-charts.md`
- `references/eks-byocni.md`
- `references/kernel-prerequisites.md`
- `references/tracing-policy-cookbook.md`
- `references/tetragon-export-modes.md`
- `references/troubleshooting.md`
