# Production troubleshooting: atl-ocp2 deployment

This annex documents the specific issues encountered during the atl-ocp2 OpenShift production deployment of the AI Pod observability stack. Each issue is presented as **symptom**, **root cause**, **fix**, and **prevention**.

## Issue 1: NIM/DCGM metrics not appearing

**Symptom**: After `helm install splunk-otel-collector ...`, the agent DaemonSet pods are running but NIM and DCGM metrics never reach O11y. SignalFlow `data('DCGM_FI_DEV_GPU_UTIL').count().publish()` returns 0.

**Root cause**: The Splunk OTel collector's ServiceAccount lacked RBAC to list endpoints in `nvidia-gpu-operator`, `nvidia-inference`, and `nvidia-nemo` namespaces. The receiver_creator silently dropped scrape targets.

**Diagnosis steps**:

```bash
# Check pod status (looks healthy)
oc -n splunk-otel get pods

# Check agent logs for forbidden errors
oc -n splunk-otel logs <agent-pod> --tail=300 | egrep 'forbidden|nvidia|dcgm'
# Found: "endpoints is forbidden: User \"system:serviceaccount:splunk-otel:splunk-otel-collector\" cannot list resource \"endpoints\" in API group \"\" in the namespace \"nvidia-gpu-operator\""

# Confirm RBAC gap
oc auth can-i --as system:serviceaccount:splunk-otel:splunk-otel-collector list endpoints -n nvidia-gpu-operator
# no
```

**Fix**: Add `rbac.customRules` to the chart values, granting `endpoints` + `endpointslices` cluster-wide:

```yaml
rbac:
  customRules:
    - apiGroups: [""]
      resources: ["endpoints"]
      verbs: ["get", "list", "watch"]
    - apiGroups: ["discovery.k8s.io"]
      resources: ["endpointslices"]
      verbs: ["get", "list", "watch"]
```

Re-run `helm upgrade`. Metrics appear within ~1 scrape cycle.

**Prevention**: The umbrella now emits `rbac.customRules` automatically when `nim_scrape_mode: endpoints` (the default). See `endpoints-rbac-patch.md`.

## Issue 2: Receiver_creator collision with chart autodetection

**Symptom**: After fixing Issue 1, DCGM metrics appear DUPLICATED in O11y — every GPU shows up twice in dashboards.

**Root cause**: The chart's `autodetect.prometheus: true` (chart default) auto-creates `receiver_creator/nvidia` for DCGM Exporter. Our renderer also creates `receiver_creator/dcgm-cisco`. Both scrape the same DCGM endpoints, producing duplicate metric series.

**Diagnosis steps**:

```bash
# Check rendered ConfigMap for both receivers
oc -n splunk-otel get cm <release>-splunk-otel-collector-agent -o jsonpath='{.data.relay}' \
  | grep -E 'receiver_creator/(nvidia|dcgm-cisco)'
# Found both.
```

**Fix**: Either disable the chart's auto-discovery for nvidia, OR accept the duplication. The umbrella chose to keep both and let SignalFlow deduplicate by `_otel_pipeline` filter when needed. See `receiver-creator-naming.md`.

**Prevention**: The umbrella's renderer always uses the unique name `receiver_creator/dcgm-cisco`, never `nvidia`. A regression test (`test_receiver_creator_name_is_never_nvidia`) prevents accidental rename.

## Issue 3: Tetragon logs missing from Splunk Platform

**Symptom**: Tetragon process-exec events configured to ship to Splunk Platform via fluentd, but no events arrive in the `cisco_isovalent` index.

**Root cause**: The Tetragon Helm chart's `export.mode: fluentd` requires a `fluent-plugin-splunk-hec` plugin which is **deprecated** and not maintained. Fluentd config silently failed to start; no error in cluster events.

**Fix**: Switched Tetragon to `export.mode: file` (writing to a hostPath mount at `/var/run/cilium/tetragon/tetragon.log`). Configured the Splunk OTel collector chart's `logsCollection.extraFileLogs.filelog/tetragon` to read the file and ship via the splunkhec exporter.

```yaml
# Tetragon Helm values
export:
  mode: file
  exportDirectory: /var/run/cilium/tetragon
  exportFilename: tetragon.log
```

```yaml
# Splunk OTel collector overlay
logsCollection:
  extraVolumes:
    - name: tetragon-logs
      hostPath: { path: /var/run/cilium/tetragon, type: Directory }
  extraVolumeMounts:
    - name: tetragon-logs
      mountPath: /var/run/cilium/tetragon
      readOnly: true
  extraFileLogs:
    filelog/tetragon:
      include: [/var/run/cilium/tetragon/*.log]
      operators: [...]
```

**Prevention**: The `splunk-observability-isovalent-integration` skill renders this exact pattern. The legacy fluentd path is gated behind `--legacy-fluentd-hec` for users who insist on it (with a banner warning of deprecation).

## Issue 4: kubeletstats receiver fails on OpenShift

**Symptom**: After deploy, the agent DaemonSet logs show `kubeletstats: x509: certificate signed by unknown authority` for every scrape cycle.

**Root cause**: OpenShift's kubelet uses an internal CA that's not in the agent pod's default CA bundle. The chart's default `kubeletStats.insecure_skip_verify: false` rejects the cert.

**Fix**: Set `kubeletStats.insecure_skip_verify: true` in the chart values overlay.

```yaml
agent:
  config:
    receivers:
      kubeletstats:
        insecure_skip_verify: true
```

**Prevention**: The umbrella's renderer auto-applies this when `--target-platform openshift`. Vanilla Kubernetes doesn't need it.

## Issue 5: Helm token in plaintext on disk

**Symptom**: A grep over the production values file (`6-splunk-otel-collector-values.yaml`) revealed a HEC token in plaintext at line 412.

**Root cause**: An operator hand-edited the values file to put the token inline instead of using the `--set splunkObservability.accessToken=$(cat $TOKEN_FILE)` pattern.

**Fix**: 

1. Rotated the leaked token immediately.
2. Removed the inline token from the values file.
3. Established the convention: NEVER hand-edit a values file with secrets; always use `helm upgrade ... --reuse-values --set ...accessToken="$(cat $TOKEN_FILE)"`.

**Prevention**: The umbrella's renderer NEVER writes tokens to the rendered overlay. The validate.sh script rejects any rendered file containing token-shaped strings. The handoff scripts include the `--set ...accessToken="$(cat $TOKEN_FILE)"` pattern explicitly.

## Issue 6: cluster-receiver pod evicted (OOMKilled)

**Symptom**: After running for ~24 hours, the cluster-receiver pod was OOMKilled. Pod restarted; metrics gap of ~30s; recurred every ~24 hours.

**Root cause**: The cluster-receiver runs the cisco_os receiver (Nexus scraper) and was buffering more metrics than its 200Mi memory limit allowed. The cisco_os receiver's per-device JSON parsing has high transient memory usage.

**Fix**: Increased the cluster-receiver's memory limit:

```yaml
clusterReceiver:
  resources:
    requests: { memory: 300Mi }
    limits: { memory: 800Mi }
```

**Prevention**: The umbrella's renderer sets reasonable defaults (300Mi/800Mi) for the cluster-receiver. For larger Nexus fleets (>10 devices, >1000 interfaces total), bump to 500Mi/1.5Gi.

## Issue 7: cert-manager conflict on cluster-receiver

**Symptom**: `helm install` fails with `Error: cert-manager: webhook returned: 500`.

**Root cause**: atl-ocp2 already had cert-manager installed cluster-wide. The chart's bundled cert-manager attempted to install a CRD that conflicted with the existing one.

**Fix**: Set `certmanager.enabled: false` in the chart values overlay.

```yaml
certmanager:
  enabled: false
```

**Prevention**: The umbrella's renderer auto-applies this when `--target-platform openshift` (atl-ocp2 was OpenShift; OpenShift typically has cert-manager pre-installed in production).

## Issue 8: cloudProvider auto-detection wrong for bare-metal

**Symptom**: The chart attempts to query EC2 IMDS / GCE metadata server to populate `cloud.`* resource attributes. Logs spam with `imds: connection timed out`.

**Root cause**: Bare-metal OpenShift has no cloud provider; the chart's auto-detection defaults to "aws" and waits for IMDS responses that never come.

**Fix**: Explicitly set `cloudProvider: ""` (empty string) in the chart values:

```yaml
cloudProvider: ""
```

**Prevention**: The umbrella's renderer auto-applies this when `--target-platform openshift-baremetal`.

## Summary of atl-ocp2 lessons codified in the umbrella


| Issue                 | Codified as                                                      |
| --------------------- | ---------------------------------------------------------------- |
| RBAC for endpoints    | `--nim-scrape-mode endpoints` triggers `rbac.customRules`        |
| Receiver collision    | Hardcoded `receiver_creator/dcgm-cisco` (never `nvidia`)         |
| Tetragon logs         | File-based via splunk-observability-isovalent-integration        |
| kubeletStats TLS      | `--target-platform openshift` sets `insecure_skip_verify: true`  |
| Helm token plaintext  | validate.sh + handoff scripts use `--set ... $(cat $TOKEN_FILE)` |
| cluster-receiver OOM  | Defaults bumped to 300Mi/800Mi                                   |
| cert-manager conflict | OpenShift target sets `certmanager.enabled: false`               |
| cloud provider        | OpenShift target sets `cloudProvider: ""`                        |


Each lesson has at least one regression test in `tests/test_splunk_observability_cisco_ai_pod_integration.py` to ensure it doesn't recur.