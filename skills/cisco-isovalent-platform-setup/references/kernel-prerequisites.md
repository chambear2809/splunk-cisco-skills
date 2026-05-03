# Kernel prerequisites

Cilium uses eBPF features that depend on Linux kernel version. The minimum kernel for Cilium v1.18.x is **5.10**. Older kernels work for older Cilium versions; the skill defaults to the v1.18.x line because that's what AWS EKS Hybrid Nodes ships.

## Per-version requirements

| Cilium version | Minimum kernel | Notes |
|----------------|----------------|-------|
| 1.18.x | 5.10 | Not supported on Ubuntu 20.04 (kernel 5.4) or RHEL 8 (kernel 4.18) per AWS docs |
| 1.17.x | 5.4 | Supported on Ubuntu 20.04, RHEL 8 |
| 1.16.x and earlier | varies | See Cilium release notes |

If you need Cilium on Ubuntu 20.04 or RHEL 8 in 2026, pin to v1.17.x; otherwise upgrade the kernel or move to a distribution with kernel >= 5.10 (Ubuntu 22.04, RHEL 9, Amazon Linux 2023, etc.).

## Preflight check

The skill's `scripts/preflight.sh` runs:

```bash
kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.nodeInfo.kernelVersion}{"\n"}{end}' \
    | awk -v min="5.10" '{split($2,a,/[.-]/); split(min,b,/[.-]/); ok=(a[1]>b[1] || (a[1]==b[1] && a[2]>=b[2])); printf "%s\t%s\t%s\n", $1, $2, ok?"OK":"WARN"}'
```

It prints one line per node with kernel version and OK/WARN. Any WARN means that node will not run Cilium v1.18.x cleanly.

## Per-feature kernel requirements

Some Cilium features require newer kernels even when the base requirement is met:

- `kubeProxyReplacement: strict` — kernel >= 5.7 for full feature parity.
- BPF-based load balancer with DSR (direct server return) — kernel >= 5.10.
- BPF host routing (`bpf.hostRouting=true`) — kernel >= 5.10.
- IPv6 BIG TCP — kernel >= 5.19 (mostly experimental in 1.18.x).
- Egress gateway with BPF mode — kernel >= 5.10.

The skill's `helm/cilium-values.yaml` defaults to `kubeProxyReplacement: strict`. If the operator is running on an older kernel, they should override to `partial` or `disabled` in the spec's `cilium` block.

## Tetragon kernel requirements

Tetragon also requires eBPF support but is more flexible:

| Tetragon feature | Minimum kernel |
|------------------|----------------|
| Process exec events | 4.18 |
| Network connect / accept events | 4.18 |
| File access events | 4.18 |
| TracingPolicy with kprobes | 5.4 |
| Layer 7 DNS / HTTP tracking | 5.10 |
| Network observability with TLS | 5.10 |

The skill's default TracingPolicy uses TCP connect/close kprobes which work on kernel >= 5.4.

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
