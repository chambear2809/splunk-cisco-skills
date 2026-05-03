# Troubleshooting

## `helm install` fails with `Cannot get repository`

```bash
helm repo update
helm repo list
```

Confirm the repo is added. If using Enterprise:

```bash
helm repo add isovalent https://helm.isovalent.com
helm repo update
helm search repo isovalent
```

If `helm search repo isovalent` returns no results, the repo URL is wrong or your network blocks `helm.isovalent.com`. Test connectivity:

```bash
curl -I https://helm.isovalent.com/index.yaml
```

## `helm install isovalent/hubble-enterprise` fails with `chart not found`

Hubble Enterprise is a private chart. The skill's `install-hubble-enterprise.sh` does NOT attempt to pull it; it prints the contact link instead. To get chart access, contact the Splunk + Isovalent team via `https://isovalent.com/splunk-contact-us/`.

Once you have access, you typically need:

1. A pull secret for the Isovalent registry: `kubectl create secret docker-registry isovalent-pull-secret --docker-server=quay.io --docker-username=... --docker-password=...`. Pass the path to this secret file as `--isovalent-pull-secret-file`.
2. License acceptance: confirm via Isovalent customer success.
3. Chart access: this may be HTTPS auth on the Helm repo or an OCI registry credential.

After access, run:

```bash
helm upgrade --install hubble-enterprise isovalent/hubble-enterprise \
  -n kube-system --create-namespace --wait \
  -f cisco-isovalent-platform-rendered/helm/hubble-enterprise-values.yaml
```

## Cilium pods crash-loop on Ubuntu 20.04 / RHEL 8

Symptom: `cilium` pods enter `CrashLoopBackOff`. Logs include `eBPF program load failed` or `kernel feature missing`.

Cause: kernel < 5.10 (Cilium v1.18.x requires 5.10+).

Fix: upgrade the kernel (`kernel-ml` from ELRepo for RHEL 8; `linux-image-generic-hwe-22.04` for Ubuntu 20.04) OR pin Cilium to v1.17.x in `cilium.image.tag`.

## `aws-node` DaemonSet still present on EKS

Cilium will not work alongside the AWS VPC CNI. Either:

1. Recreate the cluster with `eksctl ... --network-plugin none`.
2. Remove the VPC CNI (`kubectl -n kube-system delete daemonset aws-node`) — DISRUPTIVE; existing pods will lose networking until Cilium reschedules them.

The preflight script warns; do not proceed past the warning without a plan.

## Tetragon log file doesn't appear under `/var/run/cilium/tetragon/`

Symptom: `kubectl debug node/<node> --image=ubuntu -- ls /host/var/run/cilium/tetragon/` returns empty.

Possible causes:

1. Tetragon `export.mode` is not `file`. Check `helm get values tetragon -n tetragon -a` and confirm `tetragon.exportDirectory` and `tetragon.exportFilename` are set.
2. Tetragon DaemonSet hasn't rolled out yet. `kubectl -n tetragon rollout status ds/tetragon`.
3. The TracingPolicy hasn't loaded. `kubectl describe tracingpolicy network-monitoring`.
4. SELinux or AppArmor is blocking the write. Check `dmesg | grep -i denied` on the node.

## Hubble metrics on port 9965 not reachable

Cilium agent exposes Hubble metrics on the same pod IP as Cilium itself, on port 9965 (Cilium agent metrics are on 9962). Check:

```bash
CILIUM_POD_IP=$(kubectl -n kube-system get pod -l k8s-app=cilium -o jsonpath='{.items[0].status.podIP}')
kubectl run curl-test --rm -it --image=curlimages/curl --restart=Never -- curl "http://${CILIUM_POD_IP}:9965/metrics" | head -20
```

If empty, Hubble metrics may not be enabled in the Cilium values. Confirm:

```bash
helm get values cilium -n kube-system -a | grep -A 5 'hubble:'
```

The skill's defaults enable `hubble.enabled: true` and `hubble.metrics.enableOpenMetrics: true`; if the operator overrode these, re-render with the spec defaults.

## Tetragon metrics on port 2112 not reachable via `kubectl exec`

The skill explicitly does NOT use `kubectl exec ... tetragon ... 2112`. Use the API server proxy:

```bash
kubectl get --raw /api/v1/namespaces/tetragon/services/tetragon:2112/proxy/metrics | head -20
```

If this returns "service not found", the Service may not exist. Check:

```bash
kubectl -n tetragon get svc tetragon
```

If the Service is missing, the Tetragon Helm install was incomplete. Re-run `bash cisco-isovalent-platform-rendered/scripts/install-tetragon.sh`.

## `helm uninstall` doesn't remove all resources

Cilium and Tetragon ship CRDs that survive `helm uninstall`:

```bash
helm uninstall cilium -n kube-system
helm uninstall tetragon -n tetragon
# CRDs remain:
kubectl get crd | grep cilium
kubectl get crd | grep tetragon
# To fully remove (DESTRUCTIVE — also removes any custom resources of these types):
kubectl get crd -o name | grep -E 'cilium|tetragon' | xargs kubectl delete
```

Be careful: deleting CRDs deletes any `TracingPolicy`, `CiliumNetworkPolicy`, `CiliumClusterwideNetworkPolicy`, etc. resources too.
