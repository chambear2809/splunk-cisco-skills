# OBI (eBPF) Reference

**OBI** (Open Beyla Instrumentation — the Splunk-distributed OpenTelemetry Zero-code eBPF auto-instrumentation) is the language-agnostic alternative to operator + annotation injection. It runs as a DaemonSet, attaches eBPF probes to running processes on every node, and exports traces without any application-side changes, annotations, or restarts. Supported for compiled binaries (Go, C, C++, Rust) and interpreted runtimes (Java, Python, Node.js, .NET) with varying fidelity.

## When to use OBI

- Zero-code requirement (you cannot annotate / restart workloads).
- Language not supported by operator injection (Rust, C/C++).
- Sidecar patterns where an init container cannot be added (certain service-mesh-heavy deployments).

## When NOT to use OBI

- PSS `restricted` / `baseline` namespaces — OBI requires `privileged: true`.
- Kernels older than 5.8 — eBPF feature set insufficient.
- Shared clusters where kernel attach permissions are sensitive.

## DaemonSet shape

This skill renders `obi-daemonset.yaml` with:

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: splunk-obi
  namespace: splunk-otel
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: splunk-obi
  template:
    spec:
      hostPID: true
      serviceAccountName: splunk-obi
      containers:
      - name: obi
        image: ghcr.io/signalfx/splunk-otel-obi:<version>
        securityContext:
          privileged: true
          runAsUser: 0
        volumeMounts:
        - { name: security, mountPath: /sys/kernel/security, readOnly: true }
        - { name: cgroup,   mountPath: /sys/fs/cgroup,      readOnly: true }
        env:
        - name: OTEL_EXPORTER_OTLP_ENDPOINT
          value: http://$(SPLUNK_OTEL_AGENT):4317
      volumes:
      - { name: security, hostPath: { path: /sys/kernel/security } }
      - { name: cgroup,   hostPath: { path: /sys/fs/cgroup } }
```

## Namespace scoping

OBI watches every pod on every node by default. Restrict via:

- `--obi-namespaces payments,checkout` — include list.
- `--obi-exclude-namespaces kube-system,kube-public` — deny list.

Internally this renders the `OBI_INCLUDE_NAMESPACES` and `OBI_EXCLUDE_NAMESPACES` env on the DaemonSet container.

## Kernel requirements

Linux ≥ 5.8 for full feature parity. 5.4 works with reduced fidelity (no user-space tracepoints). The preflight does not probe the kernel version; operators must confirm out-of-band.

## OpenShift SCC

On OpenShift, the OBI ServiceAccount needs the `privileged` SCC. When `--distribution openshift && --enable-obi`, this skill auto-renders `openshift-scc-obi.yaml`:

```yaml
apiVersion: security.openshift.io/v1
kind: SecurityContextConstraints
metadata:
  name: splunk-obi-scc
allowPrivilegedContainer: true
allowHostPID: true
allowHostNetwork: false
readOnlyRootFilesystem: false
runAsUser:
  type: RunAsAny
seLinuxContext:
  type: RunAsAny
users:
- system:serviceaccount:splunk-otel:splunk-obi
```

Disabling `--render-openshift-scc` is a fail-render.

## Verification

```bash
kubectl -n splunk-otel get daemonset splunk-obi
kubectl -n splunk-otel logs ds/splunk-obi -c obi | tail -20
```

Look for `"probe attached"` and `"traces exported"` log lines.

## Coexistence with operator injection

OBI and the OpenTelemetry Operator can coexist on the same cluster. If a pod is both OBI-observed and operator-instrumented, you will get duplicate traces (both agents see the same requests). Pick one per namespace.

## Known limitations

- OBI cannot instrument TLS-terminated inbound traffic without visibility into the HTTPS connection — for client spans, it sees only the outbound `connect()` / `send()` syscalls.
- Go concurrency with goroutines is handled, but some deeply-nested continuations may appear as single flat spans.
- `ulimit` on open files matters for high-pod-density nodes; raise `LimitNOFILE` on the OBI DaemonSet if you see dropped spans.
