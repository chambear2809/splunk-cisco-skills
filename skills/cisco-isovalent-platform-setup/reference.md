# Cisco Isovalent Platform Setup Reference

## Source guidance

- Cilium OSS Helm chart: `helm.cilium.io` — chart `cilium/cilium`.
- Tetragon OSS Helm chart: `helm.cilium.io` — chart `cilium/tetragon` (per `tetragon.cilium.io/docs/reference/helm-chart/`).
- Isovalent Enterprise Helm repo: `helm.isovalent.com` — charts `isovalent/cilium-enterprise`, `isovalent/tetragon`, `isovalent/cilium-dnsproxy`, `isovalent/hubble-enterprise` (private), `isovalent/hubble-timescape`.
- AWS EKS Hybrid Nodes Cilium build (mirror): `oci://public.ecr.aws/eks/cilium/cilium`.
- Cisco Isovalent acquisition: completed 2024-04-12 (per `investor.cisco.com/news/news-details/2024/...`).

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
- `scripts/install-hubble-enterprise.sh` (prints the Splunk + Isovalent contact link instead of attempting to pull)
- `scripts/install-hubble-timescape.sh`
- `scripts/preflight.sh` (kernel + EKS BYOCNI + CNI conflict checks)
- `scripts/eksctl-byocni-example.sh` (when requested)
- `metadata.json`

## Setup modes

- `--render` — render Helm values + install scripts (default).
- `--apply [STEPS]` — render then apply selected install steps. Steps: `cilium, tetragon, dnsproxy, hubble-enterprise, timescape`. With no list, applies `cilium,tetragon`.
- `--validate` — run static validation against an already-rendered output.
- `--dry-run` — show the plan without writing.
- `--json` — emit JSON dry-run output.
- `--explain` — print plan in plain English.

## Edition flags

- `--edition oss` — default; uses `cilium/cilium` and `cilium/tetragon` from `helm.cilium.io`.
- `--edition enterprise` — uses `isovalent/*` from `helm.isovalent.com`. Requires `--isovalent-license-file`. Optional `--isovalent-pull-secret-file` for the private registry.
- `--eks-mirror` — use `oci://public.ecr.aws/eks/cilium/cilium` instead of the public OSS repo (EKS Hybrid Nodes).

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

- `--isovalent-license-file` (chmod 600 enforced) for the Enterprise license.
- `--isovalent-pull-secret-file` (chmod 600 enforced) for the Isovalent private registry pull secret (Docker config JSON).

Rejected direct flags: `--license`, `--license-key`, `--pull-secret`. Each error message points at the matching `--*-file` flag.

## Hubble Enterprise (private chart)

The Hubble Enterprise chart is **not publicly distributed**. The Splunking Isovalent blog (2026-02-02) explicitly says: "For information on accessing the Helm repository, contact the Splunk + Isovalent team directly via the following link: https://isovalent.com/splunk-contact-us/".

`scripts/install-hubble-enterprise.sh` prints these instructions and the install command rather than attempting to `helm pull` the chart. The values file (`helm/hubble-enterprise-values.yaml`) is rendered locally so the operator can use it once they have chart access.

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
