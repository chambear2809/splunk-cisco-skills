# Tetragon hostPath coordination

The default Splunk Platform logs path requires Tetragon (configured by `cisco-isovalent-platform-setup`) and the Splunk OTel collector (configured by this skill) to agree on a host path. This annex documents the coordination contract and how the validate scripts check it.

## The contract

Two separate Helm values must reference the same host directory:

1. `cisco-isovalent-platform-setup` -> `helm/tetragon-values.yaml`:
   ```yaml
   tetragon:
     exportDirectory: /var/run/cilium/tetragon   # Tetragon writes here
     exportFilename: tetragon.log
   ```

2. `splunk-observability-isovalent-integration` -> `splunk-otel-overlay/values.overlay.yaml`:
   ```yaml
   agent:
     extraVolumes:
       - name: tetragon
         hostPath:
           path: /var/run/cilium/tetragon         # OTel collector mounts here
       - mountPath: /var/run/cilium/tetragon     # ...inside the agent container
   logsCollection:
     extraFileLogs:
       filelog/tetragon:
         include: ['/var/run/cilium/tetragon/*.log']  # OTel reads here
   ```

If these three paths drift, Tetragon writes to one place and OTel reads from another — events are silently dropped.

## Default coordination

When both skills are run with default settings, the host path is `/var/run/cilium/tetragon`. The OTel filename glob is `*.log`, which matches Tetragon's default `tetragon.log` and any rotated files (`tetragon.log.1`, `tetragon.log.2.gz`, ...).

## Customizing the host path

If you need a non-default host path (rare; usually only when an existing Tetragon install on the cluster already uses a different path):

1. Set in `cisco-isovalent-platform-setup` spec:
   ```yaml
   tetragon:
     export:
       directory: /custom/tetragon/path
       filename: events.json
   ```

2. Set in this skill's spec:
   ```yaml
   tetragon_export:
     mode: file
     host_path: /custom/tetragon/path
     filename_pattern: "events*.json"
   ```

The validate.sh in this skill confirms `extraFileLogs.filelog/tetragon.include[0]` is under `agent.extraVolumes[0].hostPath.path`. If they don't align, validate fails with:

```
ERROR: extraFileLogs include (/var/log/tetragon/*.log) is not under hostPath (/var/run/cilium/tetragon).
```

## Permissions

The Splunk OTel collector ServiceAccount needs read permission on the hostPath. This is usually fine because:

- The collector agent runs as root by default in the Splunk OTel chart (root inside the container; node hostPath access governed by kernel).
- Tetragon writes log files with mode 0644 by default.
- OpenShift's `anyuid` SCC is required for the collector to read the hostPath as root (the platform-setup skill renders the SCC helper if `distribution: openshift`).

If the collector runs as non-root (chart override), Tetragon's log file mode + ownership must be adjusted. This is an edge case and the skill does not currently render guidance for it; see `references/troubleshooting.md` if you hit it.

## SELinux / AppArmor

On RHEL / CentOS / OpenShift, SELinux can block the hostPath mount even when the path is correct. Symptom: the collector pod starts but the filelog receiver logs `permission denied` reading the directory.

Fix: confirm the SELinux context allows read access. The standard Tetragon Helm chart sets the right context on its own files; the OTel collector mount may need an extra `seLinuxOptions` block:

```yaml
agent:
  containerSecurityContext:
    seLinuxOptions:
      type: spc_t   # privileged context, common for monitoring agents
```

This is not enabled by default; add it to the rendered overlay manually only if the SELinux denial appears in the collector logs.

## Verifying the alignment at runtime

After both skills apply, verify on a node:

```bash
# Confirm Tetragon is writing
kubectl debug node/<node> --image=ubuntu -- ls -la /host/var/run/cilium/tetragon/

# Confirm OTel collector can read
kubectl -n splunk-otel logs <collector-pod> --tail=50 | grep filelog/tetragon
```

The collector should log lines like `info filelog/tetragon@v0.X.X reading file path=/var/run/cilium/tetragon/tetragon.log`. If you see `error filelog/tetragon ... permission denied`, the SELinux/AppArmor path applies.
