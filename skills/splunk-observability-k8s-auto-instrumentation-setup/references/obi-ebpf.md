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

This skill renders `obi-daemonset.yaml` with an owned ServiceAccount followed by:

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
      nodeSelector: { kubernetes.io/os: linux }
      tolerations: [{ operator: Exists }]
      containers:
      - name: obi
        image: registry.example.test/reviewed-obi@sha256:<64-hex-digest>
        securityContext:
          privileged: true
        volumeMounts:
        - { name: kernel-security, mountPath: /sys/kernel/security }
        - { name: cgroup, mountPath: /sys/fs/cgroup }
        env:
        - name: OTEL_EXPORTER_OTLP_ENDPOINT
          value: http://$(SPLUNK_OTEL_AGENT):4317
      volumes:
      - { name: kernel-security, hostPath: { path: /sys/kernel/security } }
      - { name: cgroup, hostPath: { path: /sys/fs/cgroup } }
```

The placeholder is deliberate. This repository does not contain an audited
digest for the exact standalone OBI DaemonSet contract above, so
`--enable-obi` requires an operator-reviewed `--obi-image` digest. Mutable tags
and the legacy `--obi-version` flag are rejected.

## Namespace scoping

OBI watches every pod on every node by default. Restrict via:

- `--obi-namespaces payments,checkout` — include list.
- `--obi-exclude-namespaces kube-system,kube-public` — deny list.

Internally this renders `SPLUNK_OBI_NAMESPACE_INCLUDE` and
`SPLUNK_OBI_NAMESPACE_EXCLUDE` on the DaemonSet container.

## Kernel requirements

Linux ≥ 5.8 is the enforced production contract. Static render records it in
`metadata.json`; `validate.sh --check-obi` lists live nodes and fails unless
every Ready schedulable Linux node has a supported architecture and kernel,
and one exact-image Ready OBI pod covers each eligible node.

## OpenShift SCC

On OpenShift, the OBI ServiceAccount needs the `privileged` SCC. When `--distribution openshift && --enable-obi`, this skill auto-renders `openshift-scc-obi.yaml`:

```yaml
apiVersion: security.openshift.io/v1
kind: SecurityContextConstraints
metadata:
  name: splunk-obi-privileged
allowPrivilegedContainer: true
allowHostPID: true
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
bash skills/splunk-observability-k8s-auto-instrumentation-setup/scripts/validate.sh \
  --check-obi --kube-context <reviewed-context>
```

The gate compares live owned resources to the rendered contract, requires a
fully observed/Ready DaemonSet and complete node coverage, and checks only the
defined fatal rules over at most 200 lines from the last 10 minutes per pod
(1-MiB aggregate cap). It does not require brittle positive log strings.

For teardown, `uninstall.sh --purge-obi` first proves the exact managed config
and ownership labels, then deletes DaemonSet, optional SCC, and ServiceAccount
in that order. Drift or an unrelated same-named resource blocks deletion.

## Coexistence with operator injection

OBI and the OpenTelemetry Operator can coexist on the same cluster. If a pod is both OBI-observed and operator-instrumented, you will get duplicate traces (both agents see the same requests). Pick one per namespace.

## Known limitations

- OBI cannot instrument TLS-terminated inbound traffic without visibility into the HTTPS connection — for client spans, it sees only the outbound `connect()` / `send()` syscalls.
- Go concurrency with goroutines is handled, but some deeply-nested continuations may appear as single flat spans.
- `ulimit` on open files matters for high-pod-density nodes; raise `LimitNOFILE` on the OBI DaemonSet if you see dropped spans.
