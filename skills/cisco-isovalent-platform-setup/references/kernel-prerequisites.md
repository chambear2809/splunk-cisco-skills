# Kernel prerequisites

Cilium uses eBPF features that depend on Linux kernel version and configuration.
For the OSS Cilium 1.20.2 chart pin, upstream documents Linux kernel **5.10 or
equivalent**, including RHEL 8.10's 4.18 kernel with the required backports. The
skill's simple numeric check remains conservative and can warn on equivalent
distro kernels. The EKS Hybrid OCI mirror has separate AWS support constraints;
AWS excludes Ubuntu 20.04 and RHEL 8 for that path. Do not apply those exclusions
to every upstream Cilium installation.

## Per-version requirements

| Cilium version/path | Minimum kernel | Notes |
|---------------------|----------------|-------|
| Upstream 1.20.2 | 5.10 or distro-equivalent | RHEL 8.10's 4.18 kernel is listed as equivalent when required backports/configuration are present. |
| AWS EKS Hybrid mirror | 5.10 | AWS-specific distribution restrictions include Ubuntu 20.04 and RHEL 8; verify its current support matrix. |
| Other releases | varies | Review that exact release's upstream or provider system requirements. |

Do not use an older Cilium version solely to bypass a warning. Confirm the
kernel's distro-equivalent support and every feature-specific requirement for
the chosen chart and provider.

## Preflight check

The skill's `scripts/preflight.sh` runs:

```bash
kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.nodeInfo.kernelVersion}{"\n"}{end}' \
    | awk -v min="5.10" '{split($2,a,/[.-]/); split(min,b,/[.-]/); ok=(a[1]>b[1] || (a[1]==b[1] && a[2]>=b[2])); printf "%s\t%s\t%s\n", $1, $2, ok?"OK":"WARN"}'
```

It prints one line per node with kernel version and OK/WARN. A WARN identifies
a numeric version below the configured threshold; it does not evaluate distro
backports or prove that a kernel is unsupported. Review provider and feature
requirements before accepting or rejecting that node.

## Per-feature kernel requirements

Some Cilium features require newer kernels even when the base requirement is met:

- `kubeProxyReplacement: true` — kernel >= 5.7 for full feature parity.
- BPF-based load balancer with DSR (direct server return) — kernel >= 5.10.
- BPF host routing (`bpf.hostRouting=true`) — kernel >= 5.10.
- IPv6 BIG TCP — kernel >= 5.19.
- Egress gateway with BPF mode — kernel >= 5.10.

The skill's `helm/cilium-values.yaml` defaults to `kubeProxyReplacement: true`. If an intended kernel lacks a required capability, use a supported kernel or explicitly plan a supported kube-proxy mode in the Cilium configuration.

## Tetragon kernel requirements

Upstream Tetragon requires Linux **4.19 or newer**, BTF, and the necessary BPF
kernel configuration. Older kernels can lack individual capabilities; arm64
kernels 4.19 and 5.4 have documented limitations for some features such as
reading exec arguments. Tetragon recommends kernel 5.10 or newer for full
arm64 functionality and recommends the newest stable kernel practical for the
deployment.

Do not use a feature-by-feature minimum table as a substitute for probing the
actual kernel. Check the official Tetragon FAQ, then use `tetra probe config`
and `tetra probe` with operator-approved access when a kernel's BTF or feature
support is uncertain. The skill's bundled observe-only policies are not
validated against every kernel/distribution combination.

## Upgrading the kernel

For Ubuntu nodes:

```bash
sudo apt-get install -y linux-image-generic-hwe-22.04
sudo reboot
```

For Amazon Linux 2023:

```bash
# AL2023 ships with kernel 6.1+ by default; no upgrade needed.
```

For RHEL 8:

```bash
# Kernel 4.18 is the default; install kernel-ml from ELRepo for >= 5.x.
# OR migrate to RHEL 9 (kernel 5.14+).
```

Coordinate kernel upgrades with the cluster admin — node reboots disrupt workloads.
