# OSS vs Enterprise charts

Cisco completed the Isovalent acquisition on 2024-04-12. The chart story split into two paths that the skill exposes via `--edition oss|enterprise`.

## OSS charts (`--edition oss`, default)

| Component | Helm repo | Chart name | Exact version | License |
|-----------|-----------|------------|---:|---------|
| Cilium (CNI) | `https://helm.cilium.io` (`helm repo add cilium https://helm.cilium.io`) | `cilium/cilium` | `1.20.2` | Apache 2.0 |
| Tetragon (eBPF runtime security) | `https://helm.cilium.io` | `cilium/tetragon` | `1.7.1` | Apache 2.0 |

The OSS charts are publicly accessible; no license required. They cover the foundational CNI + runtime security functionality that pairs with `splunk-observability-isovalent-integration` for metrics scraping.

What you get with OSS:

- Full Cilium networking (`kube-proxy` replacement, network policies, identity-based security).
- Hubble metrics on port 9965 + Hubble Relay.
- Tetragon process exec / network connect / file events on port 2112.
- TracingPolicy CRDs.
- Standard Prometheus scrape endpoints.

What you do NOT get with OSS:

- Hubble Timescape (flow history beyond Relay's in-memory cache).
- Hubble Enterprise (advanced runtime security with Cisco Security Cloud App integration).
- DNS Proxy HA.
- Enterprise feature gates (e.g. `enterprise.featureGate: v1.18`).
- Cisco support contracts.

## Enterprise charts (`--edition enterprise`)

| Component | Helm repo | Chart name | Exact version | Notes |
|-----------|-----------|------------|---:|-------|
| Cilium Enterprise | `https://helm.isovalent.com` (`helm repo add isovalent https://helm.isovalent.com`) | `isovalent/cilium-enterprise` | `1.18.8` | License + optional pull secret |
| Tetragon Enterprise | `https://helm.isovalent.com` | `isovalent/tetragon` | `1.18.1` | Enterprise variant; same chart name |
| cilium-dnsproxy (DNS HA) | `https://helm.isovalent.com` | `isovalent/cilium-dnsproxy` | `1.18.8` | License required |
| **Hubble Enterprise** | `https://helm.isovalent.com` | `isovalent/hubble-enterprise` | `1.18.8` | **Private chart** — contact Isovalent for chart access |
| Hubble Timescape | `https://helm.isovalent.com` | `isovalent/hubble-timescape` | `1.18.8` | License required |

All installs resolve and apply these exact versions with atomic, wait-bound
Helm transactions. The repository does not ship upstream chart archives,
signatures, or independently audited SHA-256 values; private chart resolution
also depends on customer entitlement. Treat that as an explicit provenance gap,
not as checksum-backed supply-chain verification.

The public and Enterprise version lines are not interchangeable. The public
chart pins (`1.20.2` Cilium, `1.7.1` Tetragon) were confirmed against the
upstream chart index on 2026-09-30. Enterprise remains pinned to `1.18.8` and
`1.18.1`, the exact chart versions validated on `isovalent-demo`; these are not
asserted to be the newest Enterprise releases because the private chart index
was not independently accessible. Reconfirm those pins with entitled access
before planning an Enterprise upgrade.

Enterprise unlocks:

- Hubble Timescape: persistent flow history beyond Relay's in-memory cache; allows historical queries spanning days/weeks.
- Hubble Enterprise: deep runtime security with Cisco Security Cloud App integration via `cisco:isovalent` and `cisco:isovalent:processExec` sourcetypes.
- Cilium DNS Proxy HA: high-availability DNS visibility + policy enforcement.
- Cisco support, hardened release cadence, and roadmap alignment.

## EKS-AWS mirror (`--eks-mirror`)

For EKS Hybrid Nodes, AWS publishes a Cilium build via the OCI registry:

```bash
oci://public.ecr.aws/eks/cilium/cilium
```

This mirror is supported by AWS for the EKS Hybrid Nodes use case. The skill's `install-cilium.sh` installs exact version `1.18.8` from this OCI URL when `--eks-mirror` is set, instead of `cilium/cilium` from `helm.cilium.io`. AWS guarantees support for the AWS-published build only; if you want the upstream OSS build, omit `--eks-mirror`.

Caveats:

- This repository keeps the EKS OCI mirror at its separately reviewed `1.18.8` pin; confirm the current AWS-supported mirror versions before upgrades.
- AWS EKS Hybrid Nodes requires kernel >= 5.10 for this Cilium path and excludes Ubuntu 20.04 and RHEL 8; these AWS exclusions do not define upstream OSS distro support.

## Switching editions

When migrating from OSS to Enterprise:

1. Run the skill with `--edition enterprise --isovalent-license-file ...` to render the Enterprise values file.
2. `helm uninstall cilium -n kube-system` (the OSS install).
3. Apply the Enterprise install with `bash cisco-isovalent-platform-rendered/scripts/install-cilium.sh`.

Do **not** try to `helm upgrade cilium` from `cilium/cilium` to `isovalent/cilium-enterprise` directly — Helm refuses chart name changes.

For Tetragon the same applies: `helm uninstall tetragon -n tetragon` then `helm upgrade --install tetragon isovalent/tetragon ...`.

## Naming gotchas

- `cilium/cilium` (OSS) vs `isovalent/cilium-enterprise` (Enterprise) — the chart names differ; don't rely on `helm search repo cilium`.
- `cilium/tetragon` (OSS) vs `isovalent/tetragon` (Enterprise variant) — same chart name across repos but with different default values and image references; pick by the repo prefix.
- `isovalent/hubble-enterprise` is **not** the same as Hubble Relay or Hubble metrics — those are part of `cilium/cilium` and `isovalent/cilium-enterprise`. Hubble Enterprise is a separate product layered on top.
