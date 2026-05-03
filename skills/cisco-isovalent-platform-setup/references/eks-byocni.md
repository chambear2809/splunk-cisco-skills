# EKS BYOCNI prerequisite

Cilium on AWS EKS requires the cluster to be created with `--network-plugin none` (BYOCNI = "bring your own CNI"). Without this, the AWS VPC CNI runs alongside Cilium and traffic does not flow correctly.

## Greenfield clusters

Use the rendered `scripts/eksctl-byocni-example.sh` (run with `--render-eksctl-example`). It prints an `eksctl` cluster config:

```yaml
apiVersion: eksctl.io/v1alpha5
kind: ClusterConfig
metadata:
  name: cilium-byocni
  region: us-east-1
managedNodeGroups:
  - name: ng-1
    instanceType: m5.large
    desiredCapacity: 3
addons:
  - name: kube-proxy
  - name: coredns
```

Then:

```bash
eksctl create cluster -f cluster.yaml --without-nodegroup
eksctl create nodegroup --config-file cluster.yaml --network-plugin none
```

`--without-nodegroup` lets you skip nodegroup creation in the cluster step so the nodegroup creation can pass `--network-plugin none` independently.

## Existing clusters

If the cluster already runs the AWS VPC CNI (`aws-node` DaemonSet in `kube-system`), the rendered preflight script warns:

```
WARN: AWS VPC CNI (aws-node DaemonSet) is installed; Cilium requires BYOCNI (--network-plugin none).
```

Migration paths:

1. **Recreate the cluster** with `--network-plugin none`. Cleanest, most disruptive.
2. **In-place CNI replacement** with `cilium install --enable-aws-eni-mode --uninstall-aws-cni`. This is a Cilium CLI feature (separate from this skill) and is risky on production clusters; test on a staging cluster first.
3. **Use the EKS-AWS Cilium build** (`--eks-mirror`) which is AWS's supported alternative for Hybrid Nodes only.

The skill does not automate the in-place migration; the operator must perform it manually after the preflight warning surfaces.

## Verifying BYOCNI mode

```bash
kubectl -n kube-system get daemonset aws-node 2>&1 | grep -v 'NotFound' || echo "BYOCNI: aws-node not present"
kubectl -n kube-system get configmap amazon-vpc-cni 2>&1 | grep -v 'NotFound' || echo "BYOCNI: amazon-vpc-cni configmap not present"
```

After Cilium installs cleanly:

```bash
kubectl -n kube-system get daemonset cilium
kubectl -n kube-system rollout status ds/cilium
cilium status  # via Cilium CLI
```

## Why this matters

If you install Cilium without removing the AWS VPC CNI, you get:

- Two CNIs racing to set up pod networking.
- Pod IPs that don't route correctly.
- Hubble flows that miss most traffic (because the VPC CNI is intercepting it).
- Tetragon events that look correct (kernel-level events fire regardless of CNI), but with broken context propagation.

The preflight check catches this before install; the operator should always confirm WARN-free output before running `install-cilium.sh`.
