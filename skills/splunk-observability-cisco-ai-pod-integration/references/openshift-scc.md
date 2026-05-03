# OpenShift Security Context Constraints

OpenShift enforces stricter Pod Security than vanilla Kubernetes via Security Context Constraints (SCC). The Splunk OTel collector chart's default Pod Security Context is incompatible with the OpenShift `restricted` SCC. The umbrella ships `scripts/install-openshift-scc.sh` to apply the right SCC.

## What SCC is needed

The Splunk OTel collector agent DaemonSet needs:

- `hostNetwork: true` (to scrape kubelet on host port 10250)
- `hostPID: true` (some receivers need PID namespace access; e.g. host metrics)
- HostPath volume mount for `/var/log` (logs collection) and optionally `/var/run/cilium/tetragon` (Tetragon log file path)
- runAsUser: 0 (root) for some collector processes

These elevations exceed `restricted-v2` SCC. The umbrella's helper script creates a custom SCC `splunk-otel-collector` with exactly these privileges and binds it to the OTel collector's ServiceAccount.

## What the helper script does

```bash
#!/usr/bin/env bash
set -euo pipefail
NAMESPACE="${NAMESPACE:-splunk-otel}"

cat <<'EOF' | oc apply -f -
apiVersion: security.openshift.io/v1
kind: SecurityContextConstraints
metadata:
  name: splunk-otel-collector
allowHostDirVolumePlugin: true
allowHostNetwork: true
allowHostPID: true
allowHostPorts: true
allowHostIPC: false
allowPrivilegedContainer: false
allowedCapabilities:
  - SYS_PTRACE
defaultAddCapabilities: null
fsGroup:
  type: RunAsAny
priority: null
readOnlyRootFilesystem: false
requiredDropCapabilities: []
runAsUser:
  type: RunAsAny
seLinuxContext:
  type: RunAsAny
seccompProfiles: ["*"]
supplementalGroups:
  type: RunAsAny
volumes:
  - configMap
  - downwardAPI
  - emptyDir
  - hostPath
  - projected
  - secret
EOF

oc adm policy add-scc-to-user splunk-otel-collector -z splunk-otel-collector -n "${NAMESPACE}"
oc adm policy add-scc-to-user splunk-otel-collector -z default -n "${NAMESPACE}"
```

Apply order:

1. Create the namespace: `oc create namespace splunk-otel`.
2. Create the ServiceAccount (the chart will create it on `helm install`, but you can pre-create).
3. Run the SCC helper: `bash scripts/install-openshift-scc.sh`.
4. `helm install splunk-otel-collector ...`

## Why not use the built-in `privileged` SCC?

The `privileged` SCC grants ALL host capabilities, including `SYS_ADMIN`, full host filesystem access, and arbitrary container escape paths. Granting it to the OTel collector exceeds least privilege.

Our custom SCC narrows the privilege set to exactly what the chart needs. Specifically:

- `allowPrivilegedContainer: false` — no privileged mode.
- `allowedCapabilities: [SYS_PTRACE]` — only PTRACE for process metric collection.
- `volumes: [...]` — explicit allowlist; no `*`.

## What about the cluster-receiver pod?

The clusterReceiver Deployment doesn't need hostNetwork/hostPID. It runs under the standard `restricted-v2` SCC. The custom SCC binding scopes only to the agent DaemonSet's ServiceAccount.

If you've combined agent + clusterReceiver into one ServiceAccount (chart default), the SCC applies to both, which is fine: cluster-receiver tolerates the elevated SCC; it just doesn't need it.

## Verification

```bash
oc get scc splunk-otel-collector -o yaml
oc -n splunk-otel get pods -l component=otel-collector-agent -o jsonpath='{.items[0].spec.serviceAccountName}'
oc -n splunk-otel describe pod -l component=otel-collector-agent | grep -A 2 'Security Context'
```

Expect:

- SCC exists.
- Agent pods use ServiceAccount `splunk-otel-collector`.
- Agent pods show hostNetwork=true, hostPID=true, runAsUser=0.

## Removing the SCC binding

When uninstalling the chart, remove the SCC bindings:

```bash
oc adm policy remove-scc-from-user splunk-otel-collector -z splunk-otel-collector -n splunk-otel
oc adm policy remove-scc-from-user splunk-otel-collector -z default -n splunk-otel
oc delete scc splunk-otel-collector
```

Don't leave orphaned SCCs around; they're cluster-scoped and survive namespace deletion.

## Production atl-ocp2 lessons

The atl-ocp2 OpenShift cluster reference deployment used:

- `kubeletStats.insecure_skip_verify: true` — kubelet's TLS cert isn't always trusted by the cluster's default CA bundle. This is set in the chart values, not in SCC.
- `cloudProvider: ""` — bare-metal OpenShift (no cloud); the chart defaults assume EKS/GKE/AKS.
- `certmanager.enabled: false` — atl-ocp2 had cert-manager already; chart's bundled instance would conflict.

These are values-overlay settings, not SCC settings. The skill's renderer applies them automatically when `--target-platform openshift`.

## Anti-patterns

- **Granting `privileged` SCC system-wide**: avoid. Use the custom SCC.
- **Skipping SCC and running the chart anyway**: the agent DaemonSet pods will fail to start with `forbidden` errors. Always apply SCC first.
- **Using `oc adm policy add-scc-to-user privileged ...`**: this works but exceeds least privilege. Use our custom SCC.
