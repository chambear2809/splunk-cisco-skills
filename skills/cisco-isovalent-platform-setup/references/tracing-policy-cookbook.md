# TracingPolicy cookbook

Tetragon's `TracingPolicy` CRD attaches eBPF programs to kernel functions or syscalls and emits structured events when they fire. The skill ships a starter policy that covers TCP connect/close; this annex collects additional policies you can drop into `helm/tracing-policy.yaml` (or apply alongside it).

## Starter (rendered by default)

```yaml
apiVersion: cilium.io/v1alpha1
kind: TracingPolicy
metadata:
  name: network-monitoring
spec:
  kprobes:
  - call: tcp_connect
    syscall: false
    args:
    - index: 0
      type: sock
  - call: tcp_close
    syscall: false
    args:
    - index: 0
      type: sock
```

This produces `process_kprobe` events on every TCP connect and close, suitable for `cisco_isovalent` log analytics in Splunk Platform.

## Additional kprobe policies

### File access (security)

```yaml
apiVersion: cilium.io/v1alpha1
kind: TracingPolicy
metadata:
  name: file-access-sensitive
spec:
  kprobes:
  - call: security_file_open
    syscall: false
    args:
    - index: 0
      type: file
    selectors:
    - matchArgs:
      - index: 0
        operator: Prefix
        values:
        - /etc/shadow
        - /etc/passwd
        - /root/.ssh/
```

### Process credential changes (privilege escalation)

```yaml
apiVersion: cilium.io/v1alpha1
kind: TracingPolicy
metadata:
  name: privilege-escalation
spec:
  kprobes:
  - call: __sys_setuid
    syscall: true
  - call: __sys_setgid
    syscall: true
```

### DNS visibility (when not using cilium-dnsproxy)

```yaml
apiVersion: cilium.io/v1alpha1
kind: TracingPolicy
metadata:
  name: dns-events
spec:
  kprobes:
  - call: udp_sendmsg
    syscall: false
    selectors:
    - matchArgs:
      - index: 1
        operator: SAddr
        values:
        - "0.0.0.0/0"
      - index: 2
        operator: Equal
        values:
        - "53"
```

## Selectors and filters

Tetragon `selectors:` blocks let you constrain when the policy fires (cuts noise dramatically in production):

- `matchPIDs` — narrow by process ID range.
- `matchNamespaces` — only fire for processes in specific Linux namespaces.
- `matchCapabilities` — only fire for processes with specific Linux capabilities.
- `matchBinaries` — only fire when the process binary path matches.

Example: only fire shell-spawn events from non-root processes:

```yaml
selectors:
- matchPIDs:
  - operator: NotIn
    followForks: true
    values: [1]  # exclude PID 1 (init)
  matchBinaries:
  - operator: In
    values:
    - /bin/sh
    - /bin/bash
    - /bin/dash
```

## Production tuning

- Start narrow (specific kprobes) and add more as your detection matures.
- Use `exportDenyList` in Tetragon Helm values to suppress events from system pods (`kube-system`, `tetragon`, sidecars) — see `tetragon-export-modes.md`.
- Avoid `selectors: []` on high-frequency syscalls (`__sys_write`, `__sys_read`) — they will overwhelm the export pipeline.
- Test policies in a non-production cluster first; eBPF program load failures are silent in some Tetragon versions.

## Verifying a policy is loaded

```bash
kubectl get tracingpolicy
kubectl describe tracingpolicy network-monitoring
```

To see live events from a Tetragon pod:

```bash
# Use the API server proxy (preferred over exec):
kubectl get --raw /api/v1/namespaces/tetragon/services/tetragon:2112/proxy/metrics | head -50
```

(The skill's validation explicitly avoids `kubectl exec` patterns; the API server proxy works for metrics; for live event tailing use `tetra getevents` from the Tetragon CLI image rather than execing into the DaemonSet pod.)
