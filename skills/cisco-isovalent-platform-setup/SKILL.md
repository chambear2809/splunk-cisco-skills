---
name: cisco-isovalent-platform-setup
description: >-
  Install and operate the Isovalent platform on Kubernetes: Cilium (CNI),
  Tetragon (eBPF runtime security), and optionally Hubble Enterprise (private
  chart), cilium-dnsproxy (DNS HA), and Hubble Timescape (flow history).
  NOT a Splunk TA skill -- the `-platform-setup` suffix explicitly
  disambiguates from cisco-*-setup skills that install Splunk Platform TAs.
  Edition split via --edition oss|enterprise: OSS uses cilium/cilium and
  cilium/tetragon from helm.cilium.io (public, no license); Enterprise uses
  isovalent/* charts from helm.isovalent.com (license required, optional
  imagePullSecret). Renders kernel + EKS BYOCNI + CNI-conflict preflights.
  Tetragon export defaults to mode=file with exportDirectory=/var/run/cilium/tetragon
  so the file-based Splunk Platform integration in
  splunk-observability-isovalent-integration works out of the box. Use when
  the user asks to install Cilium / Tetragon / Hubble on K8s, set up the
  Isovalent platform, or prepare a cluster for Splunk Observability Cloud
  Isovalent integration.
---

# Cisco Isovalent Platform Setup

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
  - Requires `--isovalent-license-file`; optionally `--isovalent-pull-secret-file` for the private registry.
- **EKS-AWS mirror**: `oci://public.ecr.aws/eks/cilium/cilium` for EKS Hybrid Nodes (set `--eks-mirror`).

## Step-granular apply

`--apply <step>[,<step>...]` accepts: `cilium`, `tetragon`, `hubble-enterprise`, `dnsproxy`, `timescape`. With no list, applies the standard subset (cilium + tetragon).

## Preflights

- **Kernel >= 5.10** for Cilium v1.18.x; not supported on Ubuntu 20.04 or RHEL 8 (per AWS EKS Hybrid Nodes docs).
- **EKS BYOCNI**: Cilium on EKS requires the cluster created with `--network-plugin none`. Renderer emits a preflight warning + `eksctl` example.
- **CNI conflict**: Cilium fails if the AWS VPC CNI is still installed. Renderer warns.

## Tetragon export defaults

Tetragon Helm values default to:

```yaml
export:
  mode: file
  exportDirectory: /var/run/cilium/tetragon
  exportFilename: tetragon.log
```

This is the **production-validated path** that coordinates with `splunk-observability-isovalent-integration`'s `agent.extraVolumes` hostPath mount and `logsCollection.extraFileLogs.filelog/tetragon` block. Override with `--export-mode stdout|fluentd` for users whose SCC/PSP policies block hostPath mounts (`stdout`) or who insist on the legacy fluentd `splunk_hec` output (`fluentd` — flagged DEPRECATED, the upstream `fluent-plugin-splunk-hec` was archived 2025-06-24).

## Safety Rules

- Never ask for the Isovalent license key in conversation; never inline it.
- Use `--isovalent-license-file` (chmod 600 enforced) only.
- Use `--isovalent-pull-secret-file` (chmod 600 enforced) for the registry pull secret only.
- Reject direct license/secret flags (`--license`, `--license-key`, `--pull-secret`).
- The Hubble Enterprise chart is **private**; the renderer prints the Splunk + Isovalent contact link and writes a values file the operator can use once they have chart access. The renderer does NOT attempt to `helm pull isovalent/hubble-enterprise` directly.

## Primary Workflow

1. Choose edition and namespace layout.

2. Render:

   ```bash
   bash skills/cisco-isovalent-platform-setup/scripts/setup.sh \
     --render \
     --edition oss \
     --output-dir cisco-isovalent-platform-rendered
   ```

3. Review `cisco-isovalent-platform-rendered/`:
   - `helm/cilium-values.yaml`
   - `helm/tetragon-values.yaml`
   - `helm/tracing-policy.yaml` (starter)
   - `helm/cilium-dnsproxy-values.yaml` (Enterprise only, when --enable-dnsproxy)
   - `helm/hubble-timescape-values.yaml` (Enterprise only, when --enable-timescape)
   - `helm/hubble-enterprise-values.yaml` (Enterprise only, when --enable-hubble-enterprise; private chart contact-link surfaced in README)
   - `scripts/install-cilium.sh`, `install-tetragon.sh`, `install-cilium-dnsproxy.sh` (Ent), `install-hubble-enterprise.sh` (Ent), `install-hubble-timescape.sh` (Ent)
   - `scripts/preflight.sh` (kernel + CNI conflict + EKS BYOCNI checks)
   - `scripts/eksctl-byocni-example.sh`
   - `metadata.json`

4. Apply only when explicitly requested:

   ```bash
   bash skills/cisco-isovalent-platform-setup/scripts/setup.sh \
     --apply cilium,tetragon \
     --edition oss
   ```

   For Enterprise:

   ```bash
   bash skills/cisco-isovalent-platform-setup/scripts/setup.sh \
     --apply cilium,tetragon,hubble-enterprise,dnsproxy \
     --edition enterprise \
     --isovalent-license-file /tmp/isovalent_license \
     --isovalent-pull-secret-file /tmp/isovalent_pull_secret
   ```

## Out of scope

- Day-2 Cilium operations (CIDR migrations, BGP peer changes).
- Tetragon kernel-level debugging.
- Hubble Timescape data lifecycle (retention, S3 backup).
- AWS EKS cluster bootstrap with `--network-plugin none` (we render an `eksctl` example only).
- Splunk wiring of any kind — that's `splunk-observability-isovalent-integration`.

## Validation

```bash
bash skills/cisco-isovalent-platform-setup/scripts/validate.sh
```

Static checks confirm rendered values exist. With `--live`:

- `helm status` for every owned release.
- Pod-IP scrape probes for Cilium 9962, Hubble 9965, Cilium Envoy 9964, Cilium operator 9963, Tetragon 2112 (uses `kubectl get --raw` for Tetragon, NOT `kubectl exec`).
- Tetragon log file presence check on a node (`/var/run/cilium/tetragon/*.log`).
- Basic smoke (`cilium status`, `kubectl get crd | grep cilium`, `kubectl get tracingpolicy`).

See `reference.md` for option details and the `references/` annexes for OSS-vs-Enterprise charts, EKS BYOCNI, kernel prerequisites, TracingPolicy cookbook, Tetragon export modes, and troubleshooting.
