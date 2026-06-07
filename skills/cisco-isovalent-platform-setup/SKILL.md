---
name: cisco-isovalent-platform-setup
description: >-
  Install and operate Cisco Isovalent on Kubernetes: Cilium, Tetragon,
  Enterprise add-ons, and gated private Isovalent product packs. Renders
  OSS or Enterprise Helm assets, distribution and CNI-conflict preflights,
  feature coverage, apply plans, doctor reports, live validation, and day-2
  discover/backup/upgrade/rollback/uninstall runbooks. NOT a Splunk TA skill;
  Splunk telemetry wiring is delegated to splunk-observability-isovalent-integration.
  Use when installing or validating Cilium, Tetragon, Hubble, or Isovalent
  platform workflows on Kubernetes.
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

- `helm status` for every owned release.
- Pod-IP scrape probes for Cilium 9962, Hubble 9965, Cilium Envoy 9964, Cilium operator 9963, Tetragon 2112 (uses `kubectl get --raw` for Tetragon, NOT `kubectl exec`).
- Tetragon log file presence check on a node (`/var/run/cilium/tetragon/*.log`).
- Basic smoke (`cilium status`, `kubectl get crd | grep cilium`, `kubectl get tracingpolicy`).

See `reference.md` for option details and the `references/` annexes for OSS-vs-Enterprise charts, EKS BYOCNI, kernel prerequisites, TracingPolicy cookbook, Tetragon export modes, and troubleshooting.
