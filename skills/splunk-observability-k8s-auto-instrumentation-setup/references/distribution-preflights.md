# Distribution-Specific Preflights

Kubernetes distributions have meaningfully different networking, RBAC, and security postures that affect operator-driven auto-instrumentation. This reference catalogs every distribution-specific guard baked into the preflight catalog.

## EKS (vanilla)

- `--cluster-name` is mandatory and explicit; the offline renderer does not query EKS metadata.
- Cilium-based EKS clusters: when Cilium is NOT in ENI mode, the operator webhook on port 9443 is blocked because the pod network does not route to the EKS control plane. The preflight warns; the fix is either Cilium `--eni-mode` or setting `operator.hostNetwork: true` in the base collector chart values.

## EKS Fargate

- No DaemonSet — the agent is not reachable at `$(SPLUNK_OTEL_AGENT):4317`.
- Fail-render unless `--gateway-endpoint` is passed (points at a gateway Service DNS that Fargate pods can reach).
- Splunk EKS Fargate docs: Fargate pods MUST use a gateway-mode collector because EKS Fargate's task model has no concept of a node-local agent.

## GKE (vanilla)

- Auto-detects cluster name.
- No specific guards.

## GKE Autopilot

- Autopilot restricts some securityContexts used by operator installation Jobs. Configure and validate that base-chart concern with `splunk-observability-otel-collector-setup`; this overlay does not mutate it.
- Autopilot private clusters: port 9443 firewall rule required. Preflight warns.

## GKE Private Cluster (any variant)

- Control-plane access is restricted by default. Firewall rule required for 9443 (operator webhook). Preflight warns.

## OpenShift

- Auto-detects cluster name.
- The base collector chart renders an SCC for its own DaemonSet. OBI needs a SECOND SCC (privileged) for its eBPF daemonset. This skill auto-renders `openshift-scc-obi.yaml` when `--distribution openshift && --enable-obi`; disabling `--render-openshift-scc` is a fail-render because the OBI DaemonSet will CrashLoop.

## AKS

- No specific guards; same flow as GKE.

## Generic

- Cluster name is mandatory (no auto-detect).

## Helm v3 vs v4

- Helm/operator installation-job behavior belongs to the base collector chart workflow. Legacy installation-job inputs to this overlay fail closed.

## Architecture and OS matrix

| Language | amd64 | arm64 | Alpine/musl |
|----------|-------|-------|-------------|
| Java | yes | yes (partial; profiling limited) | yes |
| Node.js | yes | yes | yes |
| Python | yes | yes | yes (both glibc + musl shipped) |
| .NET | yes | **no** (Splunk image is amd64 only) | yes with `otel-dotnet-auto-runtime=linux-musl-x64` |
| Go | yes | yes | n/a (uses eBPF, not image-bound) |
| Apache HTTPD | yes | yes | yes |
| Nginx | yes | yes | yes |

Preflight warns on arm64 + `.NET`.

## Pod Security Standards

See [pss-and-sidecars.md](pss-and-sidecars.md).

- `restricted` or `baseline` + `--languages go` OR `--enable-obi`: fail-render (both require `privileged: true`).
- All other languages are PSS-neutral.

## Air-gapped clusters

- `--image-pull-secret my-mirror` lets the operator pull from a private mirror of `ghcr.io/signalfx/*`. The Secret itself is an operator-side responsibility; pass only the name here.
- `--java-image`, `--nodejs-image`, etc. override the image references in the CR directly. Use this when your mirror rewrites paths.
