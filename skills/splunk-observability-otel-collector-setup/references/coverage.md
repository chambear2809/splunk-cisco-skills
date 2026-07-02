# Coverage classification

Status meanings:

- **Implemented**: renderer, guarded apply, and target-specific validation exist.
- **Delegated**: another repository skill owns the complete workflow.
- **Handoff**: officially supported, but this skill emits documentation or a
  custom-config boundary rather than claiming an implementation.
- **Unsupported here**: deliberately rejected or not implemented.

## Deployment methods

| Deployment method | Status | Route / boundary |
|---|---|---|
| Kubernetes Helm chart | Implemented | Digest-verified chart `0.154.0` archive reused locally; Helm 3.9+/4 post-renderers pin every image; agent/cluster receiver/gateway; Linux or Windows releases, including FIPS variants |
| Linux DEB/RPM fresh install | Implemented | Tagged installer plus audited-only Collector and auto-instrumentation `0.154.2` executable pins |
| Linux DEB/RPM upgrade or downgrade | Handoff | The tagged installer rejects an existing Collector; use the package manager and upstream upgrade guidance |
| Linux remote SSH | Implemented | Target preflight enforces the tagged distro/arch/systemd/package-tool contract, Bash/curl/Python 3.6+/tar/SHA tooling, and noninteractive root/sudo; it rejects existing installs, validates custom-config access, and streams the token over stdin |
| TA app `7125` multi-OS package | Implemented for audit/stage | Deployment server or one Linux-capable local HF/UF package; fleet delivery/restart remains delegated |
| TA app `8698` Linux `x86_64` package | Implemented for audit/stage | Deployment server or one local Linux HF/UF package; artifact-specific digest enforced |
| TA app `8699` Windows `x86_64` package | Implemented for audit/stage | Deployment server and Agent Management only; Bash local apply intentionally rejects Windows-only packages |
| TA fleet delivery and restart | Delegated | `splunk-agent-management-setup`, `splunk-universal-forwarder-setup`, or the normal heavy-forwarder service workflow |
| Splunk Platform HEC | Delegated | `splunk-hec-service-setup` |
| Splunk Connect for OTLP receiver | Delegated | `splunk-connect-for-otlp-setup` |
| Kubernetes raw manifests | Handoff | Prefer the official Helm chart unless a GitOps owner supplies rendered manifests |
| EKS managed add-on | Handoff | Managed add-on lifecycle is provider-owned |
| EKS Auto Mode through Helm | Implemented chart topology | `distribution=eks/auto-mode`; host networking is the default resource-detection path, while gateway mode or disabled agent/cluster-receiver host networking requires EKS Pod Identity |
| EKS Fargate | Implemented chart topology | Agent disabled, gateway enabled, two-replica cluster-receiver StatefulSet; mutable upstream init image is replaced and verified by the audited post-renderer |
| GKE Autopilot / GKE ARM | Implemented chart topology | Distribution-aware chart values and multi-architecture image validation; privileged OBI/persistent queue paths remain rejected |
| AKS | Implemented chart topology | `distribution=aks` / Azure provider values; cluster-specific kubelet and identity settings remain reviewed extra values |
| OpenShift / ROSA through Helm | Implemented chart topology | `distribution=openshift`; chart SCC values are supported through guarded overlays, while OBI/SCC exceptions and platform admission evidence remain a cluster-owner handoff |
| OpenTelemetry Operator-only Collector CR | Handoff | Operator instrumentation is supported; standalone Collector CR lifecycle is not emitted |
| Windows standalone MSI/PowerShell | Handoff | Official installer path documented; no PowerShell mutation from this Bash workflow |
| Docker / Podman | Handoff | Use official image and reviewed config/secret mounts |
| ECS / EC2 / Fargate task definitions | Handoff | Use official ECS/EC2/Fargate guidance and AWS infrastructure owner |
| Nomad | Handoff | Official deployment-tool guidance |
| PCF | Handoff | Official deployment-tool guidance |
| Ansible / Chef / Puppet / Salt | Handoff | Official config-management repositories; not synthesized here |
| Chocolatey / Windows tools | Handoff | Official Windows distribution workflow |
| macOS binary | Handoff | Development-only/manual path; not a production apply target here |
| Air-gapped/private registry | Handoff | Supply reviewed mirrored image/chart/package provenance via guarded values/config |
| FedRAMP deployment | Handoff with implemented FIPS selector | `--fips-enabled` selects the audited Kubernetes FIPS image, but it does not assert FedRAMP readiness; the previously indexed dedicated Help draft is currently unavailable and internally contradicted its authorization status, so the live Marketplace package, order/contract, hosting boundary, backend/realm, integrations, and access controls require Splunk/compliance-owner evidence |

## Collector features

| Feature | Status | Notes |
|---|---|---|
| Host and Kubernetes infrastructure metrics | Implemented | Default Observability metrics path |
| OTLP traces | Implemented | Default Observability traces path |
| Container logs to HEC | Implemented | Agent DaemonSet only; file-backed token; `/event` endpoint |
| Container logs to Splunk Connect for OTLP | Implemented exporter side | Receiver setup delegated |
| Splunk Platform metrics | Implemented | Explicit HEC metric index |
| Splunk Platform traces | Experimental opt-in | Official support conflict recorded |
| HEC custom CA and mTLS | Implemented | Paired cert/key and external Secret |
| OTLP custom CA and mTLS | Implemented | Paired cert/key and external Secret |
| File-backed secrets | Implemented | Non-symlink files; mode-600 tokens/private keys; Linux/TA environment-safe token alphabet; externally created retained Kubernetes Secret |
| Extra Helm overlays | Implemented guarded extension | Immutable copied snapshot, digest recheck, YAML/schema validation, inline-secret and `secret.create=true` refusal |
| Scheduling, resources, probes, PDB, affinity, tolerations, and security context | Implemented guarded extension | Use reviewed chart values; exact rendered image and secret policy still apply, while cluster policy/admission evidence remains environment-owned |
| Outbound proxy configuration | Implemented guarded extension | Use reviewed component `extraEnvs`/configuration with Secret references where credentials are required; validate `NO_PROXY`, TLS interception, and backend reachability |
| Collector image signatures / admission policy | Handoff | All chart images are pinned and live-checked by digest; optional signature verification or admission-policy enforcement remains cluster/security-owner configuration |
| Persistent Platform exporter queue/fsync | Implemented with constraints | Requires Platform logs, a non-Autopilot Linux agent, and gateway disabled; storage planning remains operator-owned |
| Kubernetes Operator instrumentation | Implemented base chart path | Workload targeting delegated to specialized child skill |
| Operator first-install Job | Implemented for Kubernetes 1.34-1.36 | Default when instrumentation is enabled; audited kubectl `v1.35.1` image with +/-1 server-minor gate, collision ownership check, exact prior Helm/CR snapshot, expected-revision CAS rollback or new-release uninstall, and post-Helm-uninstall cleanup recheck; other server minors require a new image digest audit |
| Instrumentation resource mode | Conditional/handoff | Explicit `--instrumentation-installation-job false`; Helm 3 may use upstream resource mode, but Helm 4 first install is rejected and requires the upstream two-step operator/webhook-ready workflow |
| Existing cert-manager webhook cert | Implemented | Bundled deprecated subchart stays off |
| Kubernetes OBI | Implemented opt-in | K8s 1.24+, Linux `amd64`/`arm64`, kernel gate, host network; rejected on Fargate/Autopilot and delegated for OpenShift SCC |
| Linux-host OBI binary | Implemented install / runtime handoff | Exact `v0.6.0` pin, upstream archive checksum plus audited `amd64`/`arm64` extracted-binary digest, host prerequisites (`sha256sum` and `gzip` must preexist), optional directory, matching uninstall; no service/config/runtime orchestration |
| Target Allocator | Implemented opt-in | Requires agent metrics plus existing ServiceMonitor/PodMonitor CRDs; Prometheus ownership remains operator-reviewed |
| Network Explorer Collector profile | Implemented generic compatibility profile / eBPF handoff | `--enable-network-explorer` forces gateway mode with one replica and renders a review-only upstream eBPF chart handoff; GKE Autopilot, EKS Fargate, Windows, and OpenShift-specialized eBPF setup are rejected/delegated, and the external chart remains outside Splunk support |
| Kubernetes events/entities | Implemented experimental opt-in | Backend evidence required |
| Kubernetes control-plane metrics | Implemented chart baseline / guarded extension | Chart defaults remain active; nonstandard etcd/API-server endpoints, mTLS files, and distribution-specific settings require reviewed extra values and runtime evidence |
| Smart Agent host/application monitors | Implemented discovery gate / guarded extension | Linux discovery is explicit and custom receiver config is reviewed against the tagged component catalog; unsupported on the FIPS image and never inferred from Collector health |
| Platform logs pipeline without container collection | Implemented opt-in | `--platform-logs-enabled` supports cluster-receiver events/objects and reviewed `extraFileLogs` while container and journald sources remain independently disabled |
| Journald logs | Implemented opt-in | Linux agent + Platform logs only; units, directory, host journalctl mounts, and optional index remain reviewed extra values |
| Extra host files, multiline parsing, and annotation log filters | Guarded extension | Use reviewed extra values plus host mounts/index ownership; validate throughput and source fields |
| Platform exporter performance/field tuning | Guarded extension | Reviewed extra values may set source/sourcetype, field conventions, retry, timeout/connections, and in-memory queue sizing; destination, signals, TLS/OTLP, and persistence remain typed/protected |
| Non-root agent security context | Guarded extension | Use reviewed extra values; chart init-image and host-permission behavior must pass the pinned manifest/image checks |
| OTLP token passthrough | Guarded extension | Agent/gateway receiver metadata configuration is allowed only through reviewed extra values; validate tenant/token isolation |
| Edge Processor routing | Delegated | `splunk-edge-processor-setup`; Collector health does not prove EP pipeline readiness |
| FIPS Kubernetes image | Implemented | Audited `0.154.0` manifest covers Linux `amd64`/`arm64` and Windows `amd64`; discovery and OBI rejected |
| FIPS Linux package | Handoff | Use release FIPS artifact/manual package workflow; installer does not select it |
| Fleet Management / OpAMP | Partial/TA handoff | Entitlement and inventory evidence required |
| Gateway HA | Implemented baseline | Three replicas; PDB/HPA/topology customization through reviewed values |
| Gateway StatefulSet | Unsupported here | Not a chart `0.154.0` value |
| Tail sampling/load balancing | Handoff | Reviewed custom pipeline/gateway design required |
| Filtering/transform/redaction/routing | Handoff | Reviewed `collector-config` or guarded chart overlay; no untyped claim |
| Custom receivers/processors/exporters/connectors | Handoff | Must exist in tagged component catalog and pass Collector validation |
| Custom Linux config health | Implemented | Explicit credential-free health URL required; local and SSH status/doctor use it |
| Kubernetes Helm upgrade/status/uninstall | Implemented | Foreign same-name chart/status refusal, atomic upgrade plus expected-revision Job-owned Instrumentation rollback, uninstall-before-auxiliary-cleanup ordering, exact live image/ownership checks, retained Secret; CRD lifecycle remains separate |
| Linux fresh-install/status/uninstall | Implemented | Existing install is rejected before package mutation; exact HTTP-200 token verification is secret-safe; status requires complete journal privileges; uninstall is confirmation-gated |
| Linux upgrade/downgrade | Handoff | Not performed by this skill's installer wrappers |
| Doctor/support bundle | Implemented for Linux local and SSH | Privileged diagnostics, hash-pinned fail-closed redactor, private staging, mode-600 atomic no-replace bundle; K8s uses rollout/log/status assets |

## Product coverage

| Product | Status | Owning workflow |
|---|---|---|
| Infrastructure Monitoring | Implemented base transport | This skill |
| APM | Implemented base transport | This skill plus workload instrumentation |
| AlwaysOn Profiling | Implemented opt-in transport | Linux SDK CPU and memory profiling are independently controlled; language instrumentation required |
| Secure Application | Implemented destination toggle | Workload support/instrumentation required |
| Kubernetes Monitoring | Implemented | This skill |
| Kubernetes logs to Splunk Platform | Implemented transport | HEC or Splunk Connect for OTLP handoff; this alone does not configure Log Observer Connect |
| Log Observer Connect | Delegated | `splunk-observability-cloud-integration-setup` owns Platform pairing, service account, index mapping, and UI validation |
| Fleet Management | Partial | Entitlement-dependent OpAMP handoff |
| Database Monitoring | Delegated | `splunk-observability-database-monitoring-setup` |
| AI Agent Monitoring | Delegated | `splunk-observability-ai-agent-monitoring-setup` |
| AI Infrastructure Monitoring | Delegated | `splunk-observability-ai-agent-monitoring-setup` |
| AI Security Monitoring | Delegated | `splunk-observability-ai-agent-monitoring-setup` owns Cisco AI Defense instrumentation; require licensed integration and correlated security-span/UI evidence |
| Kubernetes zero-code app instrumentation | Delegated | `splunk-observability-k8s-auto-instrumentation-setup` |
| Generic Browser RUM / Session Replay | Delegated; bypasses Collector | `splunk-observability-browser-rum-setup` for non-Kubernetes web apps |
| Kubernetes-served Browser RUM / Session Replay | Delegated; bypasses Collector | `splunk-observability-k8s-frontend-rum-setup` |
| Mobile RUM / Session Replay | Delegated; bypasses Collector | `splunk-observability-mobile-rum-setup` |
| Synthetic Monitoring | Delegated; bypasses Collector | `splunk-observability-synthetics-setup` |
| Digital Experience Monitoring umbrella | Delegated; bypasses Collector | Browser/mobile RUM, Session Replay, and Synthetic Monitoring use their dedicated workflows and independent beacon/test evidence |
| SLOs | Delegated; bypasses Collector | `splunk-observability-slo-setup` |
| Classic dashboards and charts | Delegated; bypasses Collector | `splunk-observability-dashboard-builder` |
| Detectors, alert routing, and native operations | Delegated; bypasses Collector | `splunk-observability-native-ops` |
| Splunk On-Call / VictorOps | Delegated; bypasses Collector | `splunk-oncall-setup` owns SaaS lifecycle, integrations, paging policy, and Splunk-side companion workflows |
| DXA and deep native UI workflows | Delegated; bypasses Collector | `splunk-observability-deep-native-workflows` |
| Observability Cloud AI Assistant | Delegated; bypasses Collector | `splunk-observability-deep-native-workflows` owns scoped investigations and UI evidence |
| Observability Cloud for Mobile | Delegated; bypasses Collector | `splunk-observability-deep-native-workflows` owns mobile app dashboard/alert/push workflows |
| SignalFlow analytics, Related Content, and data tools | Delegated; downstream of collection | `splunk-observability-native-ops` and `splunk-observability-deep-native-workflows` |
| ITSI, ITE Work, and Splunk App for Content Packs | Separate Splunk Platform products | `splunk-itsi-setup` and `splunk-itsi-config`; never infer readiness from Collector health |
| Metrics Pipeline Management | Delegated; downstream of collection | `splunk-observability-metrics-pipeline-setup` |
| Splunk Platform pairing / Discover / Log Observer Connect | Delegated | `splunk-observability-cloud-integration-setup` |
| ThousandEyes integration | Delegated; direct integration bypasses Collector | `splunk-observability-thousandeyes-integration` |
| AWS Lambda APM | Delegated; Lambda layer path bypasses base Collector | `splunk-observability-aws-lambda-apm-setup` |
| Coding-agent telemetry | Delegated; destination-dependent | `splunk-observability-coding-agent-instrumentation-setup`, then Codex or Claude child skill |
| AWS integration | Delegated | `splunk-observability-aws-integration`; base skill remains the EC2/EKS host-telemetry handoff |
| Azure integration | Delegated | `splunk-observability-azure-integration`; base skill remains the AKS/host-telemetry handoff |
| GCP integration | Delegated | `splunk-observability-gcp-integration`; base skill remains the GKE/host-telemetry handoff |
| Cisco AI Pod | Delegated; composes Collector overlays | `splunk-observability-cisco-ai-pod-integration` |
| Cisco Intersight | Delegated; composes Collector overlays | `splunk-observability-cisco-intersight-integration` |
| Cisco Nexus | Delegated; composes Collector overlays | `splunk-observability-cisco-nexus-integration` |
| Isovalent / Cilium / Hubble / Tetragon | Delegated; composes Collector overlays | `splunk-observability-isovalent-integration` |
| NVIDIA GPU / DCGM | Delegated; composes Collector overlays | `splunk-observability-nvidia-gpu-integration` |
| Network Explorer | Implemented Collector compatibility / external chart handoff | This skill enforces one gateway replica and renders the upstream eBPF chart handoff for generic Linux Kubernetes; validate representative `tcp.*`/`udp.*`/`dns.*`/`http.*` metrics and the Network Explorer UI separately; OpenShift's SELinux/SCC/kernel-image path remains an explicit handoff |

## Distribution guardrails

- GKE Autopilot, EKS Fargate, OpenShift, and Windows each require their tagged
  chart distribution constraints; do not reuse a generic Linux values file.
- A Linux and Windows release must not both own the cluster receiver.
- Fargate has no DaemonSet container-log collector.
- Discovery is Linux-only and defaults off.
- OBI is Linux-only, cannot be combined with Windows/FIPS mode, and is rejected
  on EKS Fargate and GKE Autopilot; OpenShift SCC ownership is delegated.
- Windows normally uses the Windows repository; Windows FIPS uses the tagged
  multi-platform FIPS repository. Windows cannot own Operator instrumentation.
- Persistent queues require durable storage and are not assumed safe on every
  serverless/ephemeral topology.
- Only one cluster receiver should own singleton cluster metrics/events.
- CRDs are not upgraded or deleted automatically by Helm.
