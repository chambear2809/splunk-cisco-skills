# DCGM pod-label patch

DCGM Exporter v3.3.x and earlier ship without pod-level metric labels. The skill's `--enable-dcgm-pod-labels` patch enables them by granting the DCGM Exporter ServiceAccount the right RBAC + flipping the kube-state-metrics integration on.

## The problem

By default, DCGM Exporter metrics look like:

```
DCGM_FI_DEV_GPU_UTIL{gpu="0",modelName="NVIDIA H100 PCIe",Hostname="node1",UUID="GPU-..."} 75
```

Notice no `pod`, `namespace`, or `container` labels. This means you can see "GPU 0 on node1 is 75% utilized" but not "the NIM `llama-3.1-70b` workload is using 75% of GPU 0".

This breaks the per-workload AI/ML observability story. You need to be able to ask "which model is dominating GPU 0?".

## The fix

DCGM Exporter supports pod-label discovery via the kubelet device plugin. Four
pieces are required:

1. The DCGM Exporter ServiceAccount can read pods and namespaces.
2. Its projected ServiceAccount token is mounted.
3. Pod-label and pod-UID discovery environment variables are enabled.
4. `/var/lib/kubelet/pod-resources` is mounted read-only from the node.

The skill's `--enable-dcgm-pod-labels` flag renders all four pieces. A GPU
Operator-managed DaemonSet can reconcile direct patches away, so translate the
same settings into ClusterPolicy when the operator owns the workload.

## What `--enable-dcgm-pod-labels` renders

Setting `enable_dcgm_pod_labels: true` emits four files under
`dcgm-pod-labels-patch/`: ClusterRole, ClusterRoleBinding, ServiceAccount
automount, and a strategic DaemonSet env/hostPath patch. The RBAC portion is:

```yaml
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: dcgm-exporter-pod-label-reader
rules:
  - apiGroups: [""]
    resources: ["pods", "namespaces"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: dcgm-exporter-pod-label-reader
subjects:
  - kind: ServiceAccount
    name: nvidia-dcgm-exporter
    namespace: nvidia-gpu-operator
roleRef:
  kind: ClusterRole
  name: dcgm-exporter-pod-label-reader
  apiGroup: rbac.authorization.k8s.io
```

Apply all four pieces through the guarded helper:

```bash
bash skills/splunk-observability-nvidia-gpu-integration/scripts/setup.sh \
  --apply-pod-labels-patch --enable-dcgm-pod-labels --accept-k8s-apply
```

Add `--dry-run` for server-side validation without mutation. The helper waits
for the configured DaemonSet rollout and returns nonzero if it fails.

After restart, metrics should include pod labels:

```
DCGM_FI_DEV_GPU_UTIL{gpu="0",modelName="NVIDIA H100 PCIe",Hostname="node1",pod="llama-3-1-70b-abc123",namespace="nvidia-inference",container="nim"} 75
```

## Verification

1. Confirm the DaemonSet rolled:

```bash
kubectl -n nvidia-gpu-operator get pods -l app=nvidia-dcgm-exporter
```

2. Confirm pod labels now appear:

```bash
kubectl -n nvidia-gpu-operator port-forward svc/nvidia-dcgm-exporter 9400:9400 &
curl -s localhost:9400/metrics | grep DCGM_FI_DEV_GPU_UTIL | head -1
# Should show pod="..." namespace="..." container="..." labels.
```

3. Confirm metrics in O11y. SignalFlow chart:

```python
data('DCGM_FI_DEV_GPU_UTIL', filter=filter('namespace', 'nvidia-inference'))
  .sum_by(['pod'])
  .publish('per_pod_util')
```

If you see series per pod, the patch is working.

## When NOT to apply this patch

- If you're running DCGM Exporter v3.4.0+ (the GPU Operator ships v3.4.0 in chart v24.6+), the RBAC may already be in place. Check first:

```bash
kubectl get clusterrolebinding | grep dcgm
```

- If your security policy bans cluster-wide pod-list permissions for non-control-plane workloads. In that case, you'll need a Namespace-scoped RoleBinding instead, scoped to the namespaces hosting NIM/vLLM/training workloads. The skill does not currently render the namespace-scoped variant; hand-write it.

## Anti-patterns

- **Adding pod labels via the OTel `k8s_attributes` processor**: this works but adds 50-200ms of per-metric processing latency in the OTel agent. The DCGM-side patch is much faster because the kubelet device plugin caches pod metadata.
- **Granting `pods/exec` or `pods/log` to the DCGM ServiceAccount**: NEVER. The patch only needs `get/list/watch` on `pods` and `namespaces`. Anything more is privilege escalation.
