# NVIDIA GPU Operator prerequisites

The skill assumes the NVIDIA GPU Operator is already installed and healthy in the cluster. This annex documents the minimum required state.

## What the operator provides

- **NVIDIA driver** auto-installed on each GPU node (or pre-installed driver mode).
- **NVIDIA container toolkit** for runtime GPU passthrough.
- **NVIDIA device plugin** to expose GPUs as a schedulable resource (`nvidia.com/gpu`).
- **DCGM Exporter** for Prometheus metrics on each GPU node.
- **Optional**: MIG manager for Multi-Instance GPU partitioning, vGPU manager for VM passthrough, GFD (GPU Feature Discovery) for node labels.

## Install

OpenShift:

```bash
helm repo add nvidia https://helm.ngc.nvidia.com/nvidia
helm install --wait gpu-operator -n nvidia-gpu-operator --create-namespace \
  nvidia/gpu-operator \
  --set toolkit.env[0].name=CONTAINERD_CONFIG \
  --set toolkit.env[0].value=/etc/containerd/config.toml \
  --set operator.defaultRuntime=crio
```

Vanilla Kubernetes (kubeadm, kops, EKS, GKE, AKS):

```bash
helm install --wait gpu-operator -n nvidia-gpu-operator --create-namespace \
  nvidia/gpu-operator
```

Wait for all pods to be Ready:

```bash
kubectl -n nvidia-gpu-operator get pods
# Expect: gpu-operator, nvidia-driver-daemonset, nvidia-container-toolkit-daemonset,
# nvidia-device-plugin-daemonset, nvidia-dcgm-exporter, gpu-feature-discovery,
# nvidia-cuda-validator, nvidia-operator-validator
```

Verify GPUs are schedulable:

```bash
kubectl describe nodes | grep -A 5 'nvidia.com/gpu'
# Expect: capacity nvidia.com/gpu: 8 (or whatever count)
```

## DCGM Exporter Service

The skill's discovery rule matches on the DCGM Exporter Service. Confirm it exists:

```bash
kubectl -n nvidia-gpu-operator get svc nvidia-dcgm-exporter
```

Expected:

```
NAME                   TYPE        CLUSTER-IP    PORT(S)    AGE
nvidia-dcgm-exporter   ClusterIP   10.x.x.x      9400/TCP   1h
```

The Service must have selector `app: nvidia-dcgm-exporter` AND label `app.kubernetes.io/name: nvidia-dcgm-exporter`. Some older operator versions only set one of these. The skill's dual-label discovery rule handles both (see `dual-label-discovery.md`).

## EndpointSlices

The skill's receiver_creator uses `kubernetes_sd_configs` with `role: endpoints` (or `endpointslices` in newer collector versions). For this to work cluster-wide, the Splunk OTel collector ServiceAccount needs RBAC to list endpoints + endpointslices in the GPU operator namespace.

Confirm the Splunk OTel collector chart's ClusterRole grants this:

```bash
kubectl get clusterrole splunk-otel-collector -o yaml | grep -A 2 'endpoints\|endpointslices'
```

Expected (rendered by the GPU integration skill):

```yaml
- apiGroups: [""]
  resources: ["endpoints"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["discovery.k8s.io"]
  resources: ["endpointslices"]
  verbs: ["get", "list", "watch"]
```

If missing, the GPU integration skill's overlay adds an `rbac.customRules` block that the chart merges in. This is critical: without endpoint access, the receiver_creator can't discover the DCGM Exporter pods, and metrics never appear in O11y. See the AI Pod umbrella's `endpoints-rbac-patch.md` for full context.

## OpenShift / SCC considerations

On OpenShift, the GPU Operator requires SCC `nvidia-gpu-operator` (provided by the operator at install). The DCGM Exporter and driver pods run with elevated privileges; this is by design. Don't try to run them under `restricted` SCC.

The Splunk OTel collector itself does NOT need elevated SCC for GPU scraping; the receiver_creator only needs the namespace's default SCC + the RBAC above. The umbrella AI Pod skill ships an OpenShift SCC helper for the OTel collector specifically (filesystem mounts, hostNetwork, etc.); see `openshift-scc.md` in the AI Pod umbrella references.

## Multi-node clusters

Each GPU node runs its own DCGM Exporter pod. The receiver_creator discovers them via Service endpoints, so adding a new GPU node Just Works after the GPU Operator's daemonsets schedule on it (no overlay change needed).

If you have a mix of GPU and non-GPU nodes, the receiver_creator's discovery rule (`type == "pod" && labels[...]`) only matches the DCGM pods, which only exist on GPU nodes. Non-GPU nodes are correctly skipped.
