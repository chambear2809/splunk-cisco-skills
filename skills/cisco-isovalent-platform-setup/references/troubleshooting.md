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

Generated install scripts do not select repository `latest`: they run
`helm show chart ... --version <audited-version>` and pass the same exact
version to an atomic, wait/timeout-bound upgrade. If that exact version cannot
be resolved, stop and review the audited chart contract in `metadata.json`;
do not remove `--version` as a workaround.

The repo does not contain independently audited upstream chart archives,
signatures, or SHA-256 values. A successfully resolved exact version therefore
does not close the documented provenance gap, especially for private charts.

## `helm install isovalent/hubble-enterprise` fails with `chart not found`

Hubble Enterprise is a private chart. Without `--private-chart-access-verified`, the skill's `install-hubble-enterprise.sh` fails closed and prints the access runbook. To get chart access, contact the Splunk + Isovalent team via `https://isovalent.com/splunk-contact-us/`.

Once you have access, you typically need:

1. A pull secret for the Isovalent registry: `kubectl create secret docker-registry isovalent-pull-secret --docker-server=quay.io --docker-username=... --docker-password=...`. Pass the path to this secret file as `--isovalent-pull-secret-file`.
2. License acceptance: confirm via Isovalent customer success.
3. Chart access: this may be HTTPS auth on the Helm repo or an OCI registry credential.

After access, run:

```bash
bash skills/cisco-isovalent-platform-setup/scripts/setup.sh \
  --apply hubble \
  --edition enterprise \
  --kube-context prod-use1 \
  --isovalent-license-file /path/to/isovalent_license \
  --private-chart-access-verified \
  --accept-k8s-apply
```

## Cilium pods crash-loop on Ubuntu 20.04 / RHEL 8

Symptom: `cilium` pods enter `CrashLoopBackOff`. Logs include `eBPF program load failed` or `kernel feature missing`.

Cause: kernel < 5.10 (Cilium v1.18.x requires 5.10+).

Fix: upgrade the kernel (`kernel-ml` from ELRepo for RHEL 8; `linux-image-generic-hwe-22.04` for Ubuntu 20.04) OR pin Cilium to v1.17.x in `cilium.image.tag`.

## Live validation reports unsupported kubectl skew

Use a kubectl client no more than one minor version older or newer than the API
server. The validator intentionally fails before treating other evidence as a
production acceptance result. Do not suppress the check; install a compatible
client and rerun the same read-only validation.

## Enabled Enterprise add-on has no Ready pods

Hubble Enterprise and Cilium DNSProxy must be installed in their rendered
namespaces. Live validation selects pods by the exact Helm release instance and
requires every declared container in every matched pod to be Ready. A deployed
Helm status alone is insufficient. Review the add-on workload events and chart
entitlement/image-pull state before retrying; DNSProxy must additionally return
Prometheus samples on port `9967`.

DNSProxy pods use the chart's `k8s-app=cilium-dnsproxy` label, not a generic
Helm-instance label. Hubble Enterprise retains its exact
`app.kubernetes.io/instance=hubble-enterprise` selector. Each lookup uses the
independently rendered add-on namespace; standalone Timescape uses its own
namespace while Cilium-bundled Timescape remains tied to the Cilium release.

## `cilium_hive_status` reports degraded or failed

Required Cilium endpoints and enabled DNSProxy endpoints fail live validation
when they expose a positive `cilium_hive_status` sample whose `status` label is
`degraded` or `failed`. The diagnostic intentionally prints only
`cilium_hive_status`, the rule identifier, and the aggregate positive count;
it never prints other metric labels. A positive `stopped` sample is not treated
as unhealthy because stopped cells may be part of normal component lifecycle
and the skill has no source-backed rule declaring them failures.

Resolve the underlying Hive cell health before accepting the run. Do not mask
the metric, rewrite it to zero, or weaken the validator. Compare the affected
endpoint's ordinary component health and recent logs through approved,
read-only operational workflows.

## `aws-node` DaemonSet still present on EKS

Cilium will not work alongside the AWS VPC CNI. Either:

1. Recreate the cluster with `eksctl ... --network-plugin none`.
2. Remove the VPC CNI (`kubectl -n kube-system delete daemonset aws-node`) — DISRUPTIVE; existing pods will lose networking until Cilium reschedules them.

The preflight script warns; do not proceed past the warning without a plan.

## Tetragon file export is not reaching the collector

The platform validator checks the rendered file-export contract and reads a bounded 20-line tail of each Tetragon agent's ordinary pod logs through the Kubernetes pod log API. Panic, fatal, runtime-error, and export-failure matches fail closed; validator output reports rule identifiers without echoing the matched log text. It deliberately does not create a privileged node-debug pod or execute commands in workload containers. End-to-end host-file pickup belongs to `splunk-observability-isovalent-integration` validation.

Possible causes:

1. Tetragon `export.mode` is not `file`. Review `cisco-isovalent-platform-rendered/helm/tetragon-values.yaml` and confirm `tetragon.exportDirectory` and `tetragon.exportFilename` are set. Do not retrieve installed Enterprise Helm values: they can contain license material.
2. Tetragon DaemonSet hasn't rolled out yet. `kubectl -n tetragon rollout status ds/tetragon`.
3. The TracingPolicy hasn't loaded. `kubectl describe tracingpolicy network-monitoring`.
4. SELinux or AppArmor is blocking the write. Use the host's approved operating-system log workflow to inspect denial records.

## Hubble metrics on port 9965 not reachable

Cilium agent exposes Hubble metrics on port 9965 (Cilium agent metrics are on 9962). Use the same Kubernetes service API proxy path as live validation:

```bash
kubectl get --raw /api/v1/namespaces/kube-system/services/hubble-metrics:9965/proxy/metrics | head -20
```

If the service is missing or the response has no metric samples, Hubble metrics may not be enabled in the Cilium values. Confirm from the reviewed values artifact rather than retrieving installed Helm values that may include Enterprise license material:

```bash
grep -A 8 '^hubble:' cisco-isovalent-platform-rendered/helm/cilium-values.yaml
```

The skill's defaults enable `hubble.enabled: true` and `hubble.metrics.enableOpenMetrics: true`; if the operator overrode these, re-render with the spec defaults.

## Tetragon metrics on port 2112 are not reachable

Use the Kubernetes service API proxy rather than executing a command in a pod:

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
