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

DCGM Exporter v3.3.0+ supports a `--kubernetes-gpu-id-type` flag and pod-label discovery via the kubelet device plugin. Two pieces are required:

1. The DCGM Exporter pod must have RBAC to read pods + nodes.
2. The DCGM Exporter must be configured to scrape pod metadata.

The GPU Operator handles the second piece automatically when you enable pod labels. The first piece — the RBAC — is **not** included by default. The skill's `--enable-dcgm-pod-labels` flag generates the missing RBAC patch.

## What `--enable-dcgm-pod-labels` renders

Setting the flag (or `spec.dcgm_pod_labels.enabled: true` in the spec) emits `manifests/dcgm-pod-labels-rbac.yaml`:

```yaml
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: nvidia-dcgm-exporter-pod-labels
rules:
  - apiGroups: [""]
    resources: ["pods", "nodes"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: nvidia-dcgm-exporter-pod-labels
subjects:
  - kind: ServiceAccount
    name: nvidia-dcgm-exporter
    namespace: nvidia-gpu-operator
roleRef:
  kind: ClusterRole
  name: nvidia-dcgm-exporter-pod-labels
  apiGroup: rbac.authorization.k8s.io
```

Apply it:

```bash
kubectl apply -f manifests/dcgm-pod-labels-rbac.yaml
```

Then restart the DCGM Exporter pods:

```bash
kubectl -n nvidia-gpu-operator rollout restart daemonset/nvidia-dcgm-exporter
```

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
- **Granting `pods/exec` or `pods/log` to the DCGM ServiceAccount**: NEVER. The patch only needs `get/list/watch` on `pods` and `nodes`. Anything more is privilege escalation.
