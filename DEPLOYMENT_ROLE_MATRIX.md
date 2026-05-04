# Deployment Role Matrix

_Generated from `skills/shared/app_registry.json` by `skills/shared/scripts/generate_deployment_docs.py`; do not edit manually._

This document defines the repo's role-based placement model across all
supported Splunk deployment topologies.

The role matrix documents where each app or skill meaningfully belongs. The
runtime layer currently uses it for warning-only placement checks, Cloud pairing
warnings, and selected split-workflow decisions such as role-aware Stream app
installs.

## Role Definitions

| Role | Meaning |
| --- | --- |
| `search-tier` | Search heads or search-head clusters that host app UI, REST handlers, dashboards, macros, and search-time knowledge objects. |
| `indexer` | Indexing tier where index-time parsing or indexer-side knowledge objects belong. |
| `heavy-forwarder` | Customer-managed full Splunk Enterprise instance used for data collection, parsing, or forwarding. |
| `universal-forwarder` | Lightweight forwarder tier used where the package or workflow is explicitly forwarder-safe. |
| `external-collector` | Non-Splunk runtime such as SC4S, SC4SNMP, containers, or Kubernetes workloads that send data into Splunk. |

Platform and role are separate concepts:

- Platform answers whether the scripts are targeting Splunk Cloud or Splunk Enterprise APIs.
- Role answers where a package or end-to-end skill belongs inside that platform topology.
- Delivery plane answers how that package is pushed there, such as ACS, direct REST, SSH staging, deployer, or cluster-manager workflows.

For Cloud-specific install and API behavior, see
[`CLOUD_DEPLOYMENT_MATRIX.md`](CLOUD_DEPLOYMENT_MATRIX.md).

## Skill Topologies

| Skill | Search Tier | Indexer | Heavy Forwarder | Universal Forwarder | External Collector | Cloud Pairing | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `cisco-catalyst-ta-setup` | Supported | None | Supported | None | None | None | API-driven collector app; run on the search tier or a heavy forwarder you control. |
| `cisco-catalyst-enhanced-netflow-setup` | None | None | Supported | Supported | None | HF or UF | Forwarder-side field-mapping add-on for NetFlow or IPFIX receiver paths. |
| `cisco-appdynamics-setup` | Supported | None | Supported | None | None | None | Collector and dashboard setup skill; use on the search tier or a heavy forwarder. |
| `cisco-security-cloud-setup` | Supported | None | Supported | None | None | None | Product-specific Cisco Security collector app; compatible with the search tier or a heavy forwarder. |
| `cisco-secure-access-setup` | Supported | None | Supported | None | None | None | Secure Access onboarding and dashboard setup app; place on the search tier or a heavy forwarder. |
| `cisco-dc-networking-setup` | Supported | None | Supported | None | None | None | Collector app for ACI, Nexus Dashboard, and Nexus 9K data; use on the search tier or a heavy forwarder. |
| `cisco-enterprise-networking-setup` | Required | None | None | None | None | None | Search-time visualization app with macros, saved searches, and KV Store content. |
| `cisco-intersight-setup` | Supported | None | Supported | None | None | None | API collector app; run on the search tier or a heavy forwarder. |
| `cisco-meraki-ta-setup` | Supported | None | Supported | None | None | None | Meraki collector app with dashboard alignment; place on the search tier or a heavy forwarder. |
| `cisco-product-setup` | Supported | None | Supported | None | None | None | Product-name router that resolves a Cisco product from the SCAN catalog and delegates to the matching setup skill or explicit gap classification. |
| `cisco-thousandeyes-setup` | Supported | None | Supported | None | None | None | Hybrid-capable app that combines HEC push with polling and dashboard setup. |
| `splunk-app-install` | Supported | Supported | Supported | Supported | None | None | Generic package delivery skill; actual package compatibility comes from the package or app metadata. |
| `splunk-connect-for-syslog-setup` | Supported | None | None | None | Required | External collector | External collector workflow that prepares Splunk-side objects and renders SC4S runtime assets. |
| `splunk-connect-for-snmp-setup` | Supported | None | None | None | Required | External collector | External collector workflow that prepares Splunk-side objects and renders SC4SNMP runtime assets. |
| `splunk-observability-otel-collector-setup` | Supported | None | None | None | Required | External collector | External OTel Collector workflow for Kubernetes and Linux runtimes that send data to Splunk Observability Cloud and optional Splunk Platform HEC, with HEC token handoff helpers delegated to splunk-hec-service-setup. |
| `splunk-observability-k8s-auto-instrumentation-setup` | None | None | None | None | Required | External collector | Overlay on splunk-observability-otel-collector-setup. Renders per-language OpenTelemetry Operator Instrumentation CRs, workload annotation strategic-merge patches with backup/restore, OBI eBPF DaemonSet + OpenShift SCC, AlwaysOn Profiling + runtime metrics, propagator/sampler, multi-CR, Fargate gateway endpoint, vendor-coexistence detection, --discover-workloads inventory, selective --target apply/uninstall, and --gitops-mode. Never takes tokens; inherits ingest-token handling from the base collector. |
| `splunk-observability-k8s-frontend-rum-setup` | None | None | None | None | Required | External collector | Standalone reusable skill for Splunk Browser RUM (@splunk/otel-web 2.x) + Session Replay (Splunk recorder) injection into Kubernetes-served frontends. RUM beacons land directly at rum-ingest.<realm>.observability.splunkcloud.com -- no OTel collector required for browser telemetry. Four injection modes (nginx pod-side ConfigMap with sub_filter, ingress-nginx configuration-snippet annotation, busybox+emptyDir initContainer rewriter for distroless, runtime-config ConfigMap for npm-bundled SDK), full Frustration Signals 2.0 (rage / dead / error / thrashed cursor) and Session Replay (sensitivityRules + features.{canvas,video,iframes,packAssets,cacheAssets,backgroundServiceSrc} + sampler) gated behind --accept-session-replay-enterprise, JavaScript source-map upload helper wrapping the splunk-rum CLI + @splunk/rum-build-plugins Webpack plugin (reuses SPLUNK_O11Y_TOKEN_FILE), RUM-to-APM Server-Timing trace-linking validation, multi-workload spec, distroless image auto-detection, ingress-nginx CVE-2021-25742 preflight, version-pin enforcement, SRI hash emission, and --gitops-mode YAML-only rendering. Hands off RUM dashboards to splunk-observability-dashboard-builder, RUM detectors to splunk-observability-native-ops, the SIM rum modular input to splunk-observability-cloud-integration-setup, and RUM-to-APM trace linking to splunk-observability-k8s-auto-instrumentation-setup. Two credential files: SPLUNK_O11Y_RUM_TOKEN_FILE for the browser-embedded RUM token, SPLUNK_O11Y_TOKEN_FILE for the server-to-server source-map upload. Explicitly NOT AppDynamics BRUM. |
| `splunk-observability-dashboard-builder` | None | None | None | None | None | None | Splunk Observability Cloud dashboard render/apply workflow; no Splunk Platform runtime placement. |
| `splunk-observability-native-ops` | None | None | None | None | None | None | Splunk Observability Cloud native operations render/apply workflow; no Splunk Platform runtime placement. |
| `splunk-observability-cloud-integration-setup` | Required | None | Supported | None | None | Search tier | Splunk Platform <-> Splunk Observability Cloud pairing + Discover app + Log Observer Connect + Related Content + Real Time Metrics + Splunk Infrastructure Monitoring Add-on (Splunkbase 5247). Search-tier required; heavy-forwarder optional for ITSI / SIM modular-input streaming. Hands off Splunkbase install to splunk-app-install, ACS allowlist deltas to splunk-cloud-acs-allowlist-setup, and the Content Pack to splunk-itsi-config. |
| `splunk-oncall-setup` | Supported | None | Supported | None | None | Search tier or HF | Splunk On-Call (formerly VictorOps) lifecycle. Splunkbase 3546 (victorops_app) installs on a search head or SHC deployer; Splunkbase 4886 (TA-splunk-add-on-for-victorops) installs on a heavy forwarder and creates inputs for users, teams, on-call schedules, and incidents; Splunkbase 5863 (splunkoncall) is a SOAR connector. The dedicated `splunk-oncall-setup` skill is the canonical home for all Splunk On-Call work. |
| `splunk-agent-management-setup` | Supported | Supported | Supported | Supported | None | HF or UF | Agent Management control-plane workflow for server classes, deployment apps, and deployment clients; do not target indexer cluster peers or SHC members directly. |
| `splunk-universal-forwarder-setup` | None | None | None | Required | None | UF | Customer-managed Universal Forwarder runtime bootstrap and enrollment workflow; complements Agent Management server-class and deployment-app workflows. |
| `splunk-workload-management-setup` | Supported | Supported | None | None | None | None | Self-managed Enterprise Workload Management workflow for Linux search heads and indexers. |
| `splunk-hec-service-setup` | Supported | Supported | Supported | None | None | HF | Reusable HEC token and service configuration workflow for Enterprise HEC tiers or Splunk Cloud ACS-managed HEC. |
| `splunk-federated-search-setup` | Required | None | None | None | None | Search tier | Federated Search Head workflow covering Federated Search for Splunk (FSS2S, type=splunk) in standard or transparent mode and Federated Search for Amazon S3 (FSS3, type=aws_s3, Splunk Cloud only). Renders multi-provider/multi-index assets, file-based apply for Enterprise SHs and SHC deployers, REST apply for both Enterprise and Splunk Cloud, the global federated-search enable/disable switch, and a connectivityStatus probe. |
| `splunk-index-lifecycle-smartstore-setup` | None | Required | None | None | None | None | Self-managed indexer workflow for SmartStore remote volumes, retention policy, cache manager settings, and low-level remote-storage localization limits. |
| `splunk-monitoring-console-setup` | Required | None | None | None | None | None | Search-tier Monitoring Console workflow for distributed or standalone mode, distributed search groups, forwarder monitoring, platform alerts, and peer status review. |
| `splunk-enterprise-host-setup` | Supported | Supported | Supported | None | None | None | Linux host bootstrap workflow for self-managed Splunk Enterprise search tiers, indexers, cluster managers, SHC members, and heavy forwarders. |
| `splunk-enterprise-kubernetes-setup` | Supported | Supported | None | None | None | None | Self-managed Splunk Enterprise Kubernetes runtime workflow using SOK Helm assets or Splunk POD installer assets. |
| `splunk-enterprise-public-exposure-hardening` | Required | Supported | Supported | None | Supported | Search tier, HF, or External collector | On-prem Splunk Enterprise public-internet exposure hardening workflow for Splunk Web, HEC, S2S, and splunkd REST edge surfaces. Renders Splunk-side overlays plus reverse-proxy, WAF, firewall, and operator handoff assets; Cloud is not a target. |
| `splunk-platform-pki-setup` | Required | Required | Required | Supported | Supported | None | On-prem Splunk Enterprise PKI lifecycle for every TLS surface (Splunk Web 8000, splunkd REST 8089, S2S 9997, HEC 8088, KV Store, indexer cluster including replication_port-ssl 9887, SHC, License Manager, Deployment Server, Monitoring Console, Federated Search, DMZ heavy forwarder, UF fleet, Edge Processor RSA + ECDSA, SAML SP signing, LDAPS trust, splunk CLI cacert.pem). Three TLS algorithm presets (splunk-modern, fips-140-3, stig); FIPS 140-2 / 140-3 wiring via splunk-launch.conf. Cloud is not a target (Splunk Cloud manages its own TLS). |
| `splunk-itsi-setup` | Required | None | None | None | None | None | Premium search-tier app for ITSI dashboards and service analytics. |
| `splunk-itsi-config` | Required | None | None | None | None | None | Search-tier workflow for ITSI content-pack bootstrap, validation, and service-topology automation. |
| `splunk-enterprise-security-install` | Required | None | None | None | None | None | Premium search-tier SIEM app install and essinstall workflow for standalone search heads or SHC deployers. |
| `splunk-enterprise-security-config` | Required | Supported | None | None | None | Indexer | ES operational configuration workflow for search-tier objects and index-tier ES index readiness. |
| `splunk-security-portfolio-setup` | Supported | None | Supported | None | None | None | Security product router/audit workflow that resolves product names and delegates to first-class setup skills, existing ES workflows, generic install-only routes, or explicit handoff classifications. |
| `splunk-security-essentials-setup` | Required | None | None | None | None | None | Search-head-only Splunk Security Essentials app; no indexer, forwarder, or collector placement. |
| `splunk-soar-setup` | Required | Supported | None | None | Supported | Indexer or External collector | Splunk platform-side SOAR integration apps belong on search heads and, for Enterprise distributed deployments, indexers; Automation Broker and SOAR On-prem servers are represented as external-collector handoffs. |
| `splunk-license-manager-setup` | Supported | Supported | None | None | None | None | Self-managed Splunk Enterprise license manager and license peer workflow. Co-locates with cluster manager, MC, deployment server, SHC deployer, search head, or indexer. |
| `splunk-indexer-cluster-setup` | Supported | Required | None | None | None | None | Self-managed Splunk Enterprise indexer cluster bootstrap and operations workflow. Sits above splunk-enterprise-host-setup (per-host install) and emits a license-peers handoff stub for splunk-license-manager-setup. |
| `splunk-edge-processor-setup` | None | None | None | None | Supported | External collector | Splunk Edge Processor instances run as a customer-managed external collector tier (Linux, systemd / no-systemd / Docker) joined to a Splunk Cloud Platform tenant or Splunk Enterprise 10.0+ data management node. Emits an ACS allowlist handoff stub for s2s + hec features when destinations target Splunk Cloud. |
| `splunk-cloud-acs-allowlist-setup` | None | None | None | None | None | None | Splunk Cloud ACS IP allowlist control-plane workflow; manages all 7 ACS features (acs / search-api / hec / s2s / search-ui / idm-api / idm-ui) for IPv4 + IPv6. No Splunk Enterprise role placement. |
| `splunk-uba-setup` | Supported | Supported | None | None | None | Indexer | Readiness and migration workflow for existing UBA/UEBA deployments; standalone UBA server installation is not automated, and optional Kafka app placement is search-tier focused. |
| `splunk-attack-analyzer-setup` | Required | Supported | Supported | None | None | Indexer or HF | Installs the Splunk Attack Analyzer add-on and dashboard app, creates/validates the saa index, and aligns the saa_indexes macro; API credentials remain file-based handoff material. |
| `splunk-asset-risk-intelligence-setup` | Required | Supported | None | None | None | Indexer | Restricted ARI app with search-tier UI/KV Store requirements, index-tier readiness for ari_staging, ari_asset, ari_internal, and ari_ta, read-only validation, and lifecycle-complete handoffs for post-install, data sources, metrics, responses/audit, investigations, ES integration, Exposure Analytics, Add-ons, Echo, upgrade, and teardown prerequisites. |
| `splunk-ai-assistant-setup` | Required | None | None | None | None | None | Search-tier Splunk AI Assistant app with cloud-backed inference, Context and Model Runtime app UI settings, Agent Mode Cloud-region gating, and KV Store-backed local chat state. |
| `splunk-mcp-server-setup` | Required | None | None | None | None | None | Search-tier MCP service app with custom REST handlers, KV Store-backed tool metadata, encrypted token issuance, and optional local policy overlays. |
| `splunk-stream-setup` | Required | Supported | Required | Supported | None | HF or UF | Split-package Stream deployment: search-tier UI, forwarder-side capture, and optional indexer knowledge objects. |
| `cisco-spaces-setup` | Supported | None | Supported | None | None | None | Cisco Spaces firehose collector app with UCC REST handlers for stream configuration and activation token encryption. |
| `cisco-scan-setup` | Required | None | None | None | None | None | Search-head-only catalog and management app. No data ingestion — provides product catalog UI, ecosystem intelligence, and Splunkbase analytics. |
| `cisco-thousandeyes-mcp-setup` | None | None | None | None | None | None | Cisco ThousandEyes MCP Server bridge for Cursor / Claude / Codex / VS Code / AWS Kiro AI assistants. No Splunk Platform runtime placement; operator-side MCP wiring only. |
| `splunk-observability-thousandeyes-integration` | None | None | None | None | None | None | Splunk Observability Cloud <-> ThousandEyes integration via Streams API v7 (OTLP metrics) + Integrations 2.0 APM connector + full TE asset lifecycle (tests, alert rules, labels, tags, dashboards, templates). No Splunk Platform runtime placement. |
| `cisco-isovalent-platform-setup` | None | None | None | None | None | None | Isovalent platform installation lifecycle for Cilium, Hubble, and Tetragon (OSS or Enterprise editions). Renders Helm values and install/upgrade scripts; runtime targets Kubernetes, not Splunk Platform. |
| `splunk-observability-isovalent-integration` | None | None | None | None | Required | External collector | Splunk Observability Cloud + Splunk Platform integration for Isovalent (Cilium, Hubble, Tetragon). Renders OTel collector overlay (seven prometheus/isovalent_* scrape jobs + filter/includemetrics) plus file-based Tetragon log path via OTel filelog receiver and hostPath mount. Optional handoffs to splunk-hec-service-setup, splunk-observability-dashboard-builder, splunk-observability-native-ops, and cisco-security-cloud-setup. |
| `splunk-observability-cisco-nexus-integration` | None | None | None | None | Required | External collector | Splunk Observability Cloud integration for Cisco Nexus (and any cisco_os receiver-supported NX-OS / IOS-XE / IOS-XR device) metrics via the OTel cisco_os receiver in the multi-device + global-scrapers format (PR #45562, contrib v0.149.0+). Renders clusterReceiver overlay, K8s Secret manifest stub for SSH credentials, dashboards, and starter detectors. |
| `splunk-observability-cisco-intersight-integration` | None | None | None | None | Required | External collector | Splunk Observability Cloud integration for Cisco Intersight (UCS management plane) metrics via the cisco_intersight OTel receiver. Renders a separate intersight-otel namespace, K8s Secret manifest stub for the Intersight OAuth2 client, Deployment + ConfigMap shipping OTLP gRPC to the main Splunk OTel collector agent (port 4317), and dashboards / detectors. |
| `splunk-observability-nvidia-gpu-integration` | None | None | None | None | Required | External collector | Splunk Observability Cloud integration for NVIDIA GPU telemetry (DCGM Exporter). Renders receiver_creator/dcgm-cisco (custom name to avoid the chart's autodetect/nvidia collision), dual-label discovery rule, dual-pipeline filtering, and the optional --enable-dcgm-pod-labels patch (RBAC + DaemonSet env patch) to fix the GPU Operator's pod-label gap. |
| `splunk-observability-cisco-ai-pod-integration` | None | None | None | None | Required | External collector | Umbrella skill composing splunk-observability-cisco-nexus-integration, splunk-observability-cisco-intersight-integration, and splunk-observability-nvidia-gpu-integration via subprocess + Python deep-merge, then adding AI-Pod-specific blocks: NIM / vLLM / Milvus / Trident / Portworx / Redfish scrapes, dual-pipeline filtering, k8s_attributes/nim, OpenShift defaults, rbac.customRules (when --nim-scrape-mode endpoints), --workshop-mode multi-tenant pattern, and the OpenShift SCC helper. |

## App And Package Placement

| App / Package | Skill | Search Tier | Indexer | Heavy Forwarder | Universal Forwarder | External Collector |
| --- | --- | --- | --- | --- | --- | --- |
| `splunk-cisco-app-navigator` | `cisco-scan-setup` | Required | None | None | None | None |
| `TA_cisco_catalyst` | `cisco-catalyst-ta-setup` | Supported | None | Supported | None | None |
| `cisco_dc_networking_app_for_splunk` | `cisco-dc-networking-setup` | Supported | None | Supported | None | None |
| `cisco-catalyst-app` | `cisco-enterprise-networking-setup` | Required | None | None | None | None |
| `splunk_app_stream_ipfix_cisco_hsl` | `cisco-catalyst-enhanced-netflow-setup` | None | None | Supported | Supported | None |
| `CiscoSecurityCloud` | `cisco-security-cloud-setup` | Supported | None | Supported | None | None |
| `cisco-cloud-security` | `cisco-secure-access-setup` | Supported | None | Supported | None | None |
| `TA-cisco-cloud-security-addon` | `cisco-secure-access-setup` | Supported | None | Supported | None | None |
| `Splunk_TA_Cisco_Intersight` | `cisco-intersight-setup` | Supported | None | Supported | None | None |
| `Splunk_TA_AppDynamics` | `cisco-appdynamics-setup` | Supported | None | Supported | None | None |
| `Splunk_TA_cisco_meraki` | `cisco-meraki-ta-setup` | Supported | None | Supported | None | None |
| `ta_cisco_webex_add_on_for_splunk` | `splunk-app-install` | Supported | None | Supported | None | None |
| `Splunk_TA_cisco-ucs` | `splunk-app-install` | Supported | None | Supported | None | None |
| `Splunk_TA_cisco-esa` | `splunk-app-install` | Supported | Supported | Supported | None | None |
| `Splunk_TA_cisco-wsa` | `splunk-app-install` | Supported | Supported | Supported | None | None |
| `Splunk_TA_Talos_Intelligence` | `splunk-app-install` | Required | None | None | None | None |
| `splunk_app_stream` | `splunk-stream-setup` | Required | None | None | None | None |
| `Splunk_TA_stream` | `splunk-stream-setup` | None | None | Required | Supported | None |
| `Splunk_TA_stream_wire_data` | `splunk-stream-setup` | Supported | Required | Supported | None | None |
| `ta_cisco_thousandeyes` | `cisco-thousandeyes-setup` | Supported | None | Supported | None | None |
| `SA-ITOA` | `splunk-itsi-setup` | Required | None | None | None | None |
| `DA-ITSI-ContentLibrary` | `splunk-itsi-config` | Required | None | None | None | None |
| `SplunkEnterpriseSecuritySuite` | `splunk-enterprise-security-install` | Required | None | None | None | None |
| `Splunk_Security_Essentials` | `splunk-security-essentials-setup` | Required | None | None | None | None |
| `SplunkAssetRiskIntelligence` | `splunk-asset-risk-intelligence-setup` | Required | None | None | None | None |
| `Splunk Asset and Risk Intelligence Technical Add-on For Windows` | `splunk-asset-risk-intelligence-setup` | None | Supported | None | Supported | None |
| `Splunk Asset and Risk Intelligence Technical Add-on For Linux` | `splunk-asset-risk-intelligence-setup` | None | Supported | None | Supported | None |
| `Splunk Asset and Risk Intelligence Technical Add-on For macOS` | `splunk-asset-risk-intelligence-setup` | None | Supported | None | Supported | None |
| `Splunk_TA_SAA` | `splunk-attack-analyzer-setup` | Supported | None | Supported | None | None |
| `Splunk_App_SAA` | `splunk-attack-analyzer-setup` | Required | None | None | None | None |
| `splunk_app_soar` | `splunk-soar-setup` | Required | Supported | None | None | None |
| `phantom` | `splunk-soar-setup` | Required | Supported | None | None | None |
| `Splunk-UBA-SA-Kafka` | `splunk-uba-setup` | Required | None | None | None | None |
| `DA-ESS-ContentUpdate` | `splunk-enterprise-security-config` | Required | None | None | None | None |
| `Splunk_AI_Assistant_Cloud` | `splunk-ai-assistant-setup` | Required | None | None | None | None |
| `Splunk_MCP_Server` | `splunk-mcp-server-setup` | Required | None | None | None | None |
| `ta_cisco_spaces` | `cisco-spaces-setup` | Supported | None | Supported | None | None |
| `Splunk_TA_sim` | `splunk-observability-cloud-integration-setup` | Required | None | Supported | None | None |

## Notes On Split Deployments

- Splunk Cloud pairing is skill-specific, not global.
- The API-collector family can run entirely on the Cloud search tier or on a
  customer-managed heavy forwarder.
- Splunk Stream is intentionally split:
  - `splunk_app_stream` on the search tier
  - `Splunk_TA_stream` on a heavy or universal forwarder
  - `Splunk_TA_stream_wire_data` on indexers and, where useful, search or heavy-forwarder tiers
- SC4S and SC4SNMP are modeled as `external-collector` workflows rather than
  app placement inside Splunk.
