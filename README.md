# Splunk Platform and Cisco Skills

This repository is a working library of Cursor, Codex, and Claude Code agent
skills, MCP tooling, intake templates, reference docs, and shell automation for
planning, rendering, installing, configuring, validating, and handing off Splunk
Platform, Splunk Cloud, Splunk Observability Cloud, Cisco, and adjacent
operational integrations.

The catalog covers Cisco product onboarding, Splunk apps and TAs, Enterprise
Security and the broader Splunk security portfolio, ITSI, SOAR, On-Call,
Observability Cloud integrations, AI Agent Monitoring, Database Monitoring,
dashboards, detectors, OpenTelemetry collectors, Kubernetes APM
auto-instrumentation, Browser RUM and Session Replay, AWS, ThousandEyes, and
OTLP integrations, HEC, ACS allowlists, PKI, SmartStore, federated search,
workload management, Monitoring Console, license management, indexer clusters,
Edge Processor, Stream, Splunk Connect for OTLP, SC4S, SC4SNMP, Universal
Forwarders, Linux Splunk Enterprise hosts, self-managed Kubernetes runtimes, and
external-collector topologies.
Most workflows are render-first and validation-heavy, with explicit apply
phases and secret-file guardrails for production changes.

## Start With The Intake Templates

For a scannable operator view of every skill, use
[`SKILL_UX_CATALOG.md`](SKILL_UX_CATALOG.md). It gives each skill a
plain-language purpose, the best first file to open, a safe `--help` command,
the validation entry point, and the deeper docs to read next.

Before starting a setup, review the skill-local `template.example` files. They
show the non-secret information you should collect from the product domain
owners ahead of time, such as hostnames, account names, org IDs, regions,
indexes, and feature choices.

Use the relevant `skills/<skill>/template.example` as your intake worksheet,
then keep any completed copy local as `template.local` rather than committing it
to git.

The repo is designed for two use cases:

- **Agent-driven work in Cursor, Codex, or Claude Code**: the agent reads the skill metadata
  in `skills/*/SKILL.md` and runs the matching scripts for you.
- **Direct shell use**: you can run the scripts under each skill manually if you
  prefer to operate outside the agent.

Common starting points:

- If you know the Cisco product but not the Splunk app, run
  `skills/cisco-product-setup/scripts/setup.sh --dry-run`.
- If you already know the Splunkbase app or TA, use
  `skills/splunk-app-install/scripts/install_app.sh`, then run the matching
  setup skill.
- If you need Linux host bootstrap, start with
  `skills/splunk-enterprise-host-setup/`.
- If you need lightweight Universal Forwarder runtime bootstrap, start with
  `skills/splunk-universal-forwarder-setup/`; use Agent Management separately
  for server classes and deployment apps.
- If you need Splunk Enterprise on Kubernetes, start with
  `skills/splunk-enterprise-kubernetes-setup/`. The workflow renders assets by
  default and only applies them when you request an apply phase.
- If you need Splunk Enterprise Security, start with
  `skills/splunk-enterprise-security-install/` for package install and
  `skills/splunk-enterprise-security-config/` for indexes, roles, data models,
  enrichment, detections, and operational validation.
- If you need a broader Splunk security product route, start with
  `skills/splunk-security-portfolio-setup/`; it routes Enterprise Security,
  SOAR, Security Essentials, UBA, Attack Analyzer, ARI, and related offerings
  to the supported setup, install-only, or handoff path.
- If you need a broad Splunk Cloud or Enterprise administration health review,
  start with `skills/splunk-admin-doctor/`; it diagnoses admin-domain coverage
  and renders doctor reports, fix plans, and safe handoffs.
- If you need Splunk Cloud Data Manager onboarding for AWS, Azure, GCP, or
  CrowdStrike, start with `skills/splunk-cloud-data-manager-setup/`. It works
  from Data Manager-generated artifacts and keeps private Data Manager APIs out
  of scope.
- If you need Splunk Observability Cloud OTel collection on Kubernetes or a
  Linux host, start with `skills/splunk-observability-otel-collector-setup/`.
  The workflow renders Helm and Linux installer assets first, then applies only
  when requested.
- If you need OTLP senders to land in Splunk Platform through the Splunk Connect
  for OTLP modular input, start with
  `skills/splunk-connect-for-otlp-setup/`; use `skills/splunk-hec-service-setup/`
  for the HEC token prerequisite.
- If you need Splunk Observability Cloud Database Monitoring for PostgreSQL,
  Microsoft SQL Server, or Oracle Database, start with
  `skills/splunk-observability-database-monitoring-setup/`.
- If you need Splunk AI Agent Monitoring or AI Infrastructure Monitoring, start
  with `skills/splunk-observability-ai-agent-monitoring-setup/`.
- If you need AWS metrics and CloudWatch integration assets for Splunk
  Observability Cloud, start with `skills/splunk-observability-aws-integration/`.
- If you need to pair the Splunk Platform with Splunk Observability Cloud
  (Unified Identity, the Discover Splunk Observability Cloud app, Log Observer
  Connect, Related Content, the Splunk Infrastructure Monitoring Add-on), start
  with `skills/splunk-observability-cloud-integration-setup/`.
- If you need zero-code Kubernetes application auto-instrumentation (APM
  traces, AlwaysOn Profiling, runtime metrics), start with
  `skills/splunk-observability-k8s-auto-instrumentation-setup/`. For browser
  RUM and Session Replay injection into a Kubernetes-served frontend, start
  with `skills/splunk-observability-k8s-frontend-rum-setup/`.
- If you need a Cisco product wired into Splunk Observability Cloud, start with
  the matching integration skill:
  `skills/splunk-observability-cisco-nexus-integration/`,
  `skills/splunk-observability-cisco-intersight-integration/`,
  `skills/splunk-observability-nvidia-gpu-integration/`,
  `skills/splunk-observability-cisco-ai-pod-integration/`,
  `skills/splunk-observability-isovalent-integration/`, or
  `skills/splunk-observability-thousandeyes-integration/`.
- If you need Splunk Observability Cloud dashboards, use
  `skills/splunk-observability-dashboard-builder/` to turn an operational goal
  into validated classic Observability dashboard API payloads, with modern
  dashboard features called out as advisory work.
- If you need native Splunk Observability Cloud operations, use
  `skills/splunk-observability-native-ops/` for detectors, alert routing,
  Synthetics tests and artifacts, APM topology/traces, RUM sessions, modern
  logs chart handoffs, and On-Call deeplinks. For the full Splunk On-Call
  lifecycle (teams, rotations, escalation policies, routing keys, Rules
  Engine, and the Splunk-side companion apps), use
  `skills/splunk-oncall-setup/`.
- If you need to install the Isovalent platform itself (Cilium, Tetragon,
  optional Hubble Enterprise) on Kubernetes before wiring it to Splunk, start
  with `skills/cisco-isovalent-platform-setup/`.
- If you need to register the official ThousandEyes MCP Server with Cursor,
  Claude Code, Codex, VS Code, or AWS Kiro, start with
  `skills/cisco-thousandeyes-mcp-setup/`.
- If you need Splunk platform administration services, start with
  `skills/splunk-agent-management-setup/`,
  `skills/splunk-workload-management-setup/`,
  `skills/splunk-hec-service-setup/`,
  `skills/splunk-platform-restart-orchestrator/`,
  `skills/splunk-federated-search-setup/`,
  `skills/splunk-index-lifecycle-smartstore-setup/`, or
  `skills/splunk-monitoring-console-setup/`.
- If you need to build or rotate a Splunk Enterprise PKI (Private PKI, CSRs
  for a public CA, per-component certificates across Splunk Web / splunkd /
  S2S / HEC / KV Store / indexer cluster / SHC / License Manager / Deployment
  Server / Monitoring Console / Federated Search / DMZ HF / UF fleet / Edge
  Processor / SAML / LDAPS / CLI trust, FIPS wiring, or delegated rotation),
  start with `skills/splunk-platform-pki-setup/`.
- If you need self-managed license, indexer-cluster, Edge Processor, or Splunk
  Cloud ACS allowlist operations, start with
  `skills/splunk-license-manager-setup/`,
  `skills/splunk-indexer-cluster-setup/`,
  `skills/splunk-edge-processor-setup/`, or
  `skills/splunk-cloud-acs-allowlist-setup/`.
- If you need to install Splunk SOAR On-prem (single or cluster), onboard
  SOAR Cloud, stand up a Splunk SOAR Automation Broker, or install the
  Splunk-side SOAR companion apps, start with `skills/splunk-soar-setup/`.
- If you need external syslog or SNMP collection, start with
  `skills/splunk-connect-for-syslog-setup/` or
  `skills/splunk-connect-for-snmp-setup/`.
- If you need to expose an on-prem Splunk Enterprise deployment to the public
  internet, start with `skills/splunk-enterprise-public-exposure-hardening/`.
  The workflow renders Splunk-side hardening plus nginx / HAProxy / firewall /
  WAF reference templates, runs a 20-step preflight, and refuses to apply
  without `--accept-public-exposure`.

If you know the Cisco product name but not which TA or app it needs, start with
`cisco-product-setup`. It resolves the product against the packaged SCAN
catalog, points you at the right `template.example`, shows the required
configure-time fields with `--dry-run`, classifies unsupported products
explicitly, and routes automated products to the existing Cisco family
workflow.

The automation now supports two administration paths:

- **Splunk Enterprise**: direct Splunk REST API access on port `8089`, with SSH
  staging as a fallback for remote app package installs.
- **Splunk Cloud**: Admin Config Service (ACS) for app installs, index
  management, and restarts, plus search-tier REST API access on port `8089` for
  TA-specific account/input configuration after the app is installed.

For Splunk Cloud, the search-tier REST API requires the `search-api` allow list
to include your source IP. App installation, index creation, and restart
operations do **not** use the search-tier REST API in cloud mode.

## What This Repository Covers

At a high level, the repo gives you seven layers of automation:

1. **Host bootstrap**: download Splunk Enterprise or Universal Forwarder
   packages, install them on customer-managed hosts, and configure standalone
   or single-site clustered search-tier, indexer, heavy-forwarder, or
   lightweight forwarder roles.
2. **Kubernetes runtime bootstrap**: render and optionally apply Splunk
   Operator for Kubernetes or Splunk POD deployment assets for full Splunk
   Enterprise.
3. **Package delivery**: download apps from Splunkbase, fetch them from a URL,
   or install them from local `.tgz` or `.spl` files. In Splunk Cloud, installs
   are executed through ACS instead of direct `/services/apps/local` calls.
4. **App-specific setup**: create indexes, configure accounts, enable inputs,
   update macros, configure modular inputs, and apply dashboard settings. In
   Splunk Cloud, index creation uses ACS and the app-specific REST configuration
   uses the search tier.
5. **Platform administration workflows**: render and optionally apply
   self-managed Splunk Enterprise service configuration for Agent Management,
   Workload Management, Federated Search, SmartStore/index lifecycle, Monitoring
   Console, HEC service patterns, license management, indexer clusters, and the
   full Splunk Enterprise platform PKI (Private or Public PKI distributed across
   Splunk Web, splunkd, S2S, HEC, KV Store, indexer cluster replication, SHC,
   License Manager, Deployment Server, Monitoring Console, Federated Search,
   DMZ HF, UF fleet, Edge Processor, SAML, LDAPS, and CLI trust). The HEC
   service workflow can also render ACS-backed Splunk Cloud token payloads, and
   the ACS allowlist workflow manages Cloud control-plane allowlists.
6. **External collectors and observability**: render and optionally apply
   customer-managed SC4S, SC4SNMP, Splunk Edge Processor, and Splunk OTel
   Collector runtimes; configure Splunk Connect for OTLP listener placement and
   sender handoffs; wire the Splunk Platform to Splunk Observability Cloud
   (Unified Identity, Discover Splunk Observability Cloud app, Log Observer
   Connect, Splunk Infrastructure Monitoring Add-on); overlay zero-code
   Kubernetes application auto-instrumentation, Browser RUM + Session Replay
   injection, Database Monitoring, and AI Agent Monitoring; wire AWS, Cisco
   Nexus, Intersight, Isovalent, NVIDIA GPU, Cisco AI Pod, and ThousandEyes
   sources into Splunk Observability Cloud; and build reviewed Observability
   dashboard, detector, alert routing, and Splunk On-Call artifacts.
7. **Validation**: confirm the app is installed, the expected objects exist, and
   Splunk is actually receiving data.

Most of the repo follows the same pattern:

- `SKILL.md` explains when to use the skill and what values the agent may ask
  for.
- `template.example` is present in account-driven skills as a non-secret intake
  worksheet that admins can copy to `template.local` before gathering account
  details.
- `reference.md` contains vendor-specific details such as input families,
  account fields, or app behavior.
- `scripts/` contains the actual shell automation.
- `mcp_tools.json` is present for skills that expose search tooling through MCP.

This `README.md` is now the main overview document, while each `SKILL.md` and
`reference.md` carries the skill-specific details.

## Supported Skills

| Skill | Target | Main purpose |
|-------|--------|--------------|
| `cisco-product-setup` | Cisco product catalog workflow | Resolve a Cisco product name from SCAN, classify gaps, and delegate install/configure/validate to the matching Cisco setup skill |
| `cisco-scan-setup` | `splunk-cisco-app-navigator` | Install and validate the Splunk Cisco App Navigator (SCAN) catalog app; trigger catalog sync from S3 |
| `cisco-catalyst-ta-setup` | `TA_cisco_catalyst` | Configure Catalyst Center, ISE, SD-WAN, and Cyber Vision inputs |
| `cisco-catalyst-enhanced-netflow-setup` | `splunk_app_stream_ipfix_cisco_hsl` | Install and validate optional Enhanced Netflow mappings for extra dashboards |
| `cisco-appdynamics-setup` | `Splunk_TA_AppDynamics` | Configure AppDynamics controller and analytics connections, inputs, and dashboards |
| `cisco-security-cloud-setup` | `CiscoSecurityCloud` | Install and configure product-specific Cisco Security Cloud inputs with dashboard-ready defaults |
| `cisco-secure-access-setup` | `cisco-cloud-security` + `TA-cisco-cloud-security-addon` | Install and configure Secure Access org accounts, event add-on prerequisites, app settings, and dashboard prerequisites |
| `cisco-webex-setup` | `ta_cisco_webex_add_on_for_splunk` + `cisco_webex_meetings_app_for_splunk` | Configure Webex OAuth accounts, dashboard indexes/macros, and REST inputs for meetings, audit, qualities, calling, generic endpoints, and Contact Center |
| `cisco-ucs-ta-setup` | `Splunk_TA_cisco-ucs` | Configure UCS Manager server records, default/custom templates, cisco_ucs_task inputs, and cisco:ucs validation |
| `cisco-secure-email-web-gateway-setup` | `Splunk_TA_cisco-esa` + `Splunk_TA_cisco-wsa` | Configure ESA/WSA add-ons, email/netproxy indexes, macros, parser placement, and SC4S/file-monitor ingestion handoffs |
| `cisco-talos-intelligence-setup` | `Splunk_TA_Talos_Intelligence` | Validate Enterprise Security Cloud Talos service account readiness, custom REST/capability mapping, alert actions, and threatlist state |
| `cisco-spaces-setup` | `ta_cisco_spaces` | Configure Cisco Spaces meta stream accounts, firehose inputs, and activation tokens |
| `cisco-dc-networking-setup` | `cisco_dc_networking_app_for_splunk` | Configure ACI, Nexus Dashboard, and Nexus 9K data collection |
| `cisco-intersight-setup` | `Splunk_TA_Cisco_Intersight` | Configure Cisco Intersight account, index, and inputs |
| `cisco-meraki-ta-setup` | `Splunk_TA_cisco_meraki` | Configure Meraki organization account, index, and polling inputs |
| `cisco-enterprise-networking-setup` | `cisco-catalyst-app` | Configure the visualization app’s macros and related app settings |
| `cisco-thousandeyes-setup` | `ta_cisco_thousandeyes` | Configure ThousandEyes OAuth, HEC, streaming/polling inputs, and dashboards |
| `cisco-thousandeyes-mcp-setup` | Official ThousandEyes MCP Server (`https://api.thousandeyes.com/mcp`) | Render and apply Model Context Protocol client configurations for Cursor / Claude Code / Codex / VS Code / AWS Kiro; gates the write/Instant-Test tool group behind `--accept-te-mcp-write-tools` |
| `cisco-isovalent-platform-setup` | Cilium / Tetragon / Hubble Enterprise on Kubernetes (NOT a Splunk TA installer) | Install the Isovalent platform itself: OSS (`cilium/cilium` + `cilium/tetragon` from `helm.cilium.io`) or Enterprise (`isovalent/*` from `helm.isovalent.com`, license + private chart access). Tetragon export defaults to `mode: file` for `splunk-observability-isovalent-integration`. |
| `splunk-itsi-setup` | `SA-ITOA` | Install and validate Splunk ITSI; integration readiness for ThousandEyes |
| `splunk-itsi-config` | Native ITSI objects, service trees, and supported ITSI content packs | Preview, apply, and validate ITSI entities, services, KPIs, dependencies, template links, service trees, NEAPs, and selected content packs from YAML specs |
| `splunk-enterprise-security-install` | `SplunkEnterpriseSecuritySuite` | Install, post-install, and validate Splunk Enterprise Security on standalone search heads or SHC deployers |
| `splunk-enterprise-security-config` | Splunk Enterprise Security configuration | Configure ES indexes, roles, data models, enrichment, detections, and operational validation |
| `splunk-security-portfolio-setup` | Splunk security product router | Resolve ES, SOAR, Security Essentials, UBA, Attack Analyzer, ARI, and related security offerings to setup, install-only, bundled ES, or handoff workflows |
| `splunk-security-essentials-setup` | `Splunk_Security_Essentials` | Install and validate Splunk Security Essentials, content recommendations, and starter posture dashboards |
| `splunk-asset-risk-intelligence-setup` | `SplunkAssetRiskIntelligence` | Install ARI app `7180`, prepare/validate `ari_staging`, `ari_asset`, `ari_internal`, and `ari_ta`, check KV Store, ARI roles/capabilities, saved searches, `ari_ta` data, and ES hints, then hand off post-install config, usage data review, event searches, data source priorities, metric exceptions, responses, audit, troubleshooting, release notes, normal ES risk factors, ES 8.5+ Exposure Analytics, ARI Add-ons `7214`/`7416`/`7417`, ARI Echo, upgrade, and uninstall prerequisites |
| `splunk-attack-analyzer-setup` | `Splunk_TA_SAA` + `Splunk_App_SAA` | Install and validate Attack Analyzer platform integration, the `saa` index, `saa_indexes` macro, and API key handoff |
| `splunk-uba-setup` | Splunk UBA / UEBA readiness | Validate legacy UBA integrations, optional Kafka app placement, and ES Premier UEBA migration handoff |
| `splunk-ai-assistant-setup` | `Splunk_AI_Assistant_Cloud` | Install and configure Splunk AI Assistant (formerly Splunk AI Assistant for SPL); drive Enterprise cloud-connected onboarding |
| `splunk-mcp-server-setup` | `Splunk_MCP_Server` | Install and configure Splunk MCP Server settings, tokens, and shared Cursor/Codex/Claude Code bridge bundles |
| `splunk-admin-doctor` | Splunk Cloud and Enterprise admin health | Diagnose full admin-domain coverage, render doctor/fix-plan reports, create safe fix packets or handoffs, and run checkpointed live validation sweeps |
| `splunk-cloud-data-manager-setup` | Splunk Cloud Platform Data Manager | Render, doctor, validate, and safely apply supported Data Manager-generated AWS CloudFormation/StackSet, Azure ARM, and GCP Terraform artifacts; covers AWS, Azure, GCP, and CrowdStrike onboarding, HEC/index readiness, source catalogs, migration guardrails, and UI handoffs without private Data Manager API or Terraform CRUD claims |
| `splunk-app-install` | Any app or TA | Install, list, or uninstall Splunk apps |
| `splunk-universal-forwarder-setup` | Splunk Universal Forwarder runtime | Bootstrap Linux, macOS, and rendered Windows Universal Forwarders; enroll clients with deployment server, static indexers, or Splunk Cloud credentials package |
| `splunk-agent-management-setup` | Splunk Agent Management | Render, apply, and validate server classes, deployment apps, and deployment client assets |
| `splunk-workload-management-setup` | Splunk Workload Management | Render and validate workload pools, workload rules, admission-rule guardrails, and Linux workload prerequisites |
| `splunk-hec-service-setup` | Splunk HTTP Event Collector | Prepare reusable HEC token configuration, allowed indexes, Enterprise inputs.conf assets, and Splunk Cloud ACS payloads |
| `splunk-platform-restart-orchestrator` | Splunk Platform restart and reload operations | Plan, validate, audit, and safely execute Splunk Cloud ACS restarts, Enterprise systemd/CLI restarts, deployment-server reloads, and cluster-aware restart handoffs |
| `splunk-connect-for-otlp-setup` | `splunk-connect-for-otlp` | Install, configure, validate, diagnose, and repair Splunk Connect for OTLP app `8704`; render OTLP sender configs and HEC-token handoffs without exposing token values |
| `splunk-federated-search-setup` | Splunk Federated Search | Render and validate self-managed Splunk-to-Splunk standard or transparent providers, standard-mode federated indexes, and SHC replication assets |
| `splunk-index-lifecycle-smartstore-setup` | Splunk Index Lifecycle / SmartStore | Render and validate SmartStore `indexes.conf`, `server.conf`, and `limits.conf` assets for indexers or cluster managers |
| `splunk-monitoring-console-setup` | Splunk Monitoring Console | Render and validate self-managed distributed or standalone Monitoring Console assets, including auto-config, peer/group review, forwarder monitoring, and platform alerts |
| `splunk-enterprise-host-setup` | Splunk Enterprise runtime | Bootstrap Linux Splunk Enterprise hosts as search-tier, indexer, heavy-forwarder, cluster-manager, indexer-peer, SHC deployer, or SHC member |
| `splunk-enterprise-kubernetes-setup` | Splunk Enterprise on Kubernetes | Render, preflight, apply, and validate SOK S1/C3/M4 or Splunk POD on Cisco UCS |
| `splunk-observability-otel-collector-setup` | Splunk Observability Cloud OTel Collector | Render, apply, and validate Splunk Distribution of OpenTelemetry Collector assets for Kubernetes clusters and Linux hosts, including Splunk Platform HEC token handoff helpers |
| `splunk-observability-ai-agent-monitoring-setup` | Splunk AI Agent Monitoring + AI Infrastructure Monitoring | Render, validate, diagnose, and safely apply AI Agent Monitoring setup plans, including GenAI Python instrumentation packages, instrumentation-side evaluations, histogram collector readiness, HEC/Log Observer Connect handoffs, dashboards, detectors, and full AI Infrastructure Monitoring product coverage |
| `splunk-observability-database-monitoring-setup` | Splunk Observability Cloud Database Monitoring | Render and validate DBMon collector overlays for PostgreSQL, Microsoft SQL Server, and Oracle Database through the Splunk OTel Collector; enforces realm, version, support-matrix, clusterReceiver, and secret-handling guardrails |
| `splunk-observability-k8s-auto-instrumentation-setup` | Zero-code K8s app auto-instrumentation | Overlay on `splunk-observability-otel-collector-setup`: render, apply, verify, and uninstall per-language OpenTelemetry Operator Instrumentation CRs, workload annotation patches, OBI, AlwaysOn Profiling, runtime metrics, vendor-coexistence detection, workload discovery, selective target apply/uninstall, and `--gitops-mode` YAML-only rendering |
| `splunk-observability-k8s-frontend-rum-setup` | Splunk Browser RUM + Session Replay for Kubernetes-served frontends | Render, apply, verify, and uninstall Browser RUM injection across nginx, ingress-nginx, initContainer rewrite, and runtime-config modes; includes Frustration Signals, gated Session Replay, source-map upload helpers, RUM-to-APM Server-Timing validation, GitOps rendering, and handoffs to dashboard, detector, SIM, and auto-instrumentation workflows |
| `splunk-observability-cloud-integration-setup` | Splunk Platform <-> Splunk Observability Cloud | Pair Splunk Cloud Platform / Splunk Enterprise with Splunk Observability Cloud end-to-end: token-auth flip, Unified Identity or Service Account pairing, multi-org default-org, Centralized RBAC, Discover Splunk Observability Cloud app's five Configurations tabs, Log Observer Connect (SCP + SE TLS), Related Content + Real Time Metrics, Dashboard Studio O11y metrics, and the Splunk Infrastructure Monitoring Add-on (Splunk_TA_sim, 5247) install + account + curated SignalFlow modular inputs |
| `splunk-observability-thousandeyes-integration` | ThousandEyes -> Splunk Observability Cloud | Render and apply the full TE -> O11y wiring: Integration 1.0 OpenTelemetry stream (`POST /v7/streams` to ingest.<realm>.signalfx.com/v2/datapoint/otlp), Integrations 2.0 Splunk Observability APM connector, full TE asset lifecycle (tests, alert rules, labels, tags, TE-side dashboards, Templates with Handlebars-only credential placeholders); per-test-type SignalFlow dashboards + detectors handed off to `splunk-observability-dashboard-builder` and `splunk-observability-native-ops` |
| `splunk-observability-isovalent-integration` | Isovalent (Cilium / Hubble / Tetragon) -> Splunk Observability Cloud + Splunk Platform | Render the Splunk OTel collector overlay (seven `prometheus/isovalent_*` scrape jobs + `filter/includemetrics` + cilium-dnsproxy fix); Splunk Platform logs DEFAULT via OTel filelog receiver + hostPath mount + `extraFileLogs.filelog/tetragon` (production-validated); legacy fluentd splunk_hec behind `--legacy-fluentd-hec` (DEPRECATED); hands off Tetragon log ingestion to `cisco-security-cloud-setup` (`PRODUCT=isovalent`, sourcetype `cisco:isovalent`, index `cisco_isovalent`) |
| `splunk-observability-cisco-nexus-integration` | Cisco Nexus 9000 fabric -> Splunk Observability Cloud | Standalone reusable: clusterReceiver `cisco_os` overlay (PR #45562 multi-device + global-scrapers format, contrib v0.149.0+) with K8s Secret manifest stub for SSH credentials, dashboards (port utilization, errors, drops, CPU/memory) and detectors (interface down, packet drop rate, CPU/memory pressure). Companion to `cisco-dc-networking-setup` (Splunk Platform TA path). |
| `splunk-observability-cisco-intersight-integration` | Cisco Intersight (UCS) -> Splunk Observability Cloud | Standalone reusable: separate `intersight-otel` namespace + Secret manifest stub + Deployment + ConfigMap pointing at the Splunk OTel agent's OTLP gRPC endpoint; dashboards (UCS power/thermal/fan/network/alarms/advisories/VM count) and detectors (alarm spike, security advisory delta, host temp/power, fan failure). Companion to `cisco-intersight-setup` (Splunk Platform TA path). |
| `splunk-observability-nvidia-gpu-integration` | NVIDIA GPUs (DCGM Exporter) -> Splunk Observability Cloud | Standalone reusable: `receiver_creator/dcgm-cisco` (parameterized; explicitly NOT `receiver_creator/nvidia` to avoid collision with chart autodetect); dual-label DCGM discovery (`app` + `app.kubernetes.io/name`); default unfiltered `metrics/nvidia-metrics` pipeline; `--enable-dcgm-pod-labels` patch (env-var + RBAC + SA-token + kubelet mount) for the well-known GPU Operator pod-label gap. Works for any GPU cluster (NVIDIA DGX, AI Pod, generic K8s + GPUs). |
| `splunk-observability-cisco-ai-pod-integration` | Cisco AI Pod (UCS + Nexus + NVIDIA GPUs + NIM/vLLM + storage) -> Splunk Observability Cloud | Umbrella that composes Nexus + Intersight + NVIDIA GPU components via subprocess + Python deep-merge AND adds NIM scrape (TWO modes: `receiver_creator` simple vs `endpoints` precise + `rbac.customRules` patch), vLLM, Milvus, NetApp Trident (port 8001), Pure Portworx (17001+17018), Redfish exporter (user-supplied), `k8s_attributes/nim` for `model_name` extraction, dual-pipeline filtering pattern, OpenShift defaults (kubeletstats `insecure_skip_verify`, certmanager off, cloudProvider empty), `--workshop-mode` multi-tenant.sh, OpenShift SCC helper. Mirrors `signalfx/splunk-opentelemetry-examples/collector/cisco-ai-ready-pods` + production-validated atl-ocp2 OpenShift cluster. |
| `splunk-observability-aws-integration` | AWS -> Splunk Observability Cloud | Standalone reusable: render, apply, validate, discover, and diagnose the `AWSCloudWatch` integration end-to-end across polling, Splunk-managed Metric Streams, AWS-managed Metric Streams, and Terraform. Emits IAM policy JSON, regional or StackSets CloudFormation stubs, Splunk-side Terraform, API payloads, drift reports, and handoffs for AWS logs, Lambda APM, dashboards, detectors, and EC2/EKS host telemetry. |
| `splunk-observability-dashboard-builder` | Splunk Observability Cloud dashboards | Render, validate, and optionally apply classic Observability dashboard groups, charts, and dashboards from natural-language, JSON, or YAML specs |
| `splunk-observability-native-ops` | Splunk Observability Cloud native operations | Render, validate, and optionally apply supported native Observability operations for detectors, alert routing, Synthetics, APM, RUM, logs, and On-Call handoffs |
| `splunk-oncall-setup` | Splunk On-Call (formerly VictorOps) | Render, validate, and apply On-Call teams, users, rotations, escalation policies, routing keys, incidents, REST/email alert payloads, and Splunk-side companion app handoffs |
| `splunk-stream-setup` | Splunk Stream stack | Install and configure Splunk Stream components |
| `splunk-connect-for-syslog-setup` | SC4S external collector | Prepare Splunk HEC/indexes and render or apply Docker, Podman, systemd, or Helm assets for Splunk Connect for Syslog |
| `splunk-connect-for-snmp-setup` | SC4SNMP external collector | Prepare Splunk HEC/indexes and render or apply Docker Compose or Helm assets for Splunk Connect for SNMP |
| `splunk-license-manager-setup` | Splunk Enterprise license manager / peers / pools / groups / messages | Install licenses, switch groups, configure peers, allocate pools, audit usage and violations, validate version compatibility |
| `splunk-soar-setup` | `splunk_soar-unpriv` (single + cluster) + `splunk_app_soar` (6361) + Splunk App for SOAR Export (3411) + Splunk SOAR Automation Broker | Install SOAR On-prem (single + cluster with external PG/GlusterFS/Elasticsearch), help with SOAR Cloud onboarding, install Automation Broker on Docker/Podman, install Splunk-side SOAR apps, ready ES integration, backup/restore |
| `splunk-edge-processor-setup` | Splunk Edge Processor instances + cloud / Enterprise control plane | Add EP control-plane object, install instances on Linux (systemd or not), scale to multi-instance, manage source types / destinations / SPL2 pipelines, apply pipelines, validate health |
| `splunk-indexer-cluster-setup` | Splunk Enterprise indexer cluster (single-site, multisite, redundant managers) | Bootstrap manager(s) / peers / SHs, manage cluster bundle (validate / apply / rollback), rolling restart (default / searchable / forced), peer offline (fast / enforce-counts), maintenance mode, single-site to multisite migration, manager replacement |
| `splunk-cloud-acs-allowlist-setup` | Splunk Cloud ACS IP allowlists (all 7 features, IPv4 + IPv6) | Render plan, preflight (subnet limits, lock-out protection, FedRAMP carve-out), apply, audit / diff, optional Terraform emission |
| `splunk-enterprise-public-exposure-hardening` | On-prem Splunk Enterprise public-internet exposure | Render Splunk-side hardening (web/server/inputs/outputs/authentication/authorize/limits/commands.conf + metadata) plus reverse-proxy (nginx/HAProxy) + firewall + WAF/CDN handoff; preflight 20-step + validate live probes; SVD floor enforcement; refuses to apply without `--accept-public-exposure` |
| `splunk-platform-pki-setup` | Splunk Enterprise platform PKI lifecycle | Render Private PKI or Public PKI assets, distribute per-component certificates across Splunk Web, splunkd, S2S, HEC, KV Store, indexer clusters, SHC, License Manager, Deployment Server, Monitoring Console, Federated Search, DMZ HF, UF fleet, Edge Processor, SAML, LDAPS, and CLI trust; enforce TLS presets, FIPS wiring, KV Store EKU rules, mTLS opt-in, and delegated rotation runbooks |

## Vendor Package Policy

This repo now treats `splunk-ta/` as the local package cache and review cache,
not as the only cloud deployment source.

- **Enterprise install path**: install the original `.tgz`, `.tar.gz`, `.rpm`,
  `.deb`, or `.spl` package from `splunk-ta/`, a remote URL, or Splunkbase.
- **Cloud install path**: for apps published on Splunkbase, prefer ACS
  Splunkbase installs and let ACS fetch the latest compatible release. Use
  private package uploads only for genuinely private or pre-vetted apps that do
  not have a public Splunkbase install path.
- **Registry-backed cloud installs**: when a local package matches an entry in
  `skills/shared/app_registry.json`, the cloud installer prefers ACS
  Splunkbase installs, applies any required license acknowledgement, resolves
  declared companion-package dependencies, and verifies that the deployed app
  identity matches the expected package.
- **No extract/repack required**: unpacked app trees are not part of the normal
  deployment workflow.
- **Review-only unpacked copies**: anything under `splunk-ta/_unpacked/` is for
  static review and risk analysis only.
- **Vendor package constraints**: if a package is not Splunk Cloud-compatible as
  shipped, that is treated as a vendor/package limitation rather than something
  this repo silently fixes at install time.

See `DEPLOYMENT_ROLE_MATRIX.md` for cross-platform role placement and
`CLOUD_DEPLOYMENT_MATRIX.md` for the Cloud-specific deployment model.

## Platform And Role

This repo now separates two different questions:

- **Platform target**: are the scripts talking to Splunk Cloud APIs or a
  self-managed Splunk Enterprise management endpoint?
- **Deployment role**: where does the app or workflow belong inside the target
  topology?

The shared helpers still resolve the **platform** (`cloud` or `enterprise`).
The package registry and role matrix now describe the **deployment role** using
five role names:

- `search-tier`
- `indexer`
- `heavy-forwarder`
- `universal-forwarder`
- `external-collector`

Role support is package- and skill-specific. The repo does **not** assume that
every app or workflow belongs on every tier just because the overall deployment
contains that tier.

Declare the current runtime role with `SPLUNK_TARGET_ROLE` when you want
warning-only placement checks during install, setup, and validation. If
`SPLUNK_SEARCH_PROFILE` points at a paired target, use
`SPLUNK_SEARCH_TARGET_ROLE` to declare that paired role explicitly. You can
also use `SPLUNK_SEARCH_TARGET_ROLE` as a pairing hint when the companion
runtime is outside the current Splunk management target, such as an SC4S or
SC4SNMP external collector. Environment variables override the selected
profile's role
metadata for the current run. In Cloud mode, warning-only checks stay anchored
to the Cloud search tier unless you switch the run to the paired Enterprise
target.

Runtime role is also not the same thing as the delivery plane. A package may be
validated as `search-tier`, for example, even when the admin action that
delivers it comes through ACS, a deployer, or another control-plane path.

## How To Use This Repo

The normal app and TA workflow is:

1. Configure credentials once.
2. Install the app or TA from Splunkbase (latest version). If Splunkbase is
   unavailable, fall back to local packages in `splunk-ta/`.
3. Run the skill-specific setup script.
4. Validate the deployment.
5. Restart Splunk if the setup script tells you to. The generic install/uninstall
   scripts already restart Splunk automatically unless you explicitly skip it.

Kubernetes and external-collector workflows are different: they usually render
reviewable runtime assets first, then optionally run a preflight, apply, or live
status phase after an operator reviews the generated files.

### 1. Configure Credentials

All scripts load deployment settings from a project-root `credentials` file
first, fall back to `~/.splunk/credentials` if the project file does not exist,
and honor `SPLUNK_CREDENTIALS_FILE` when you want to point a run at an
alternate credentials file entirely.

The simplest setup path is:

```bash
bash skills/shared/scripts/setup_credentials.sh
```

Or copy the template and edit it yourself:

```bash
cp credentials.example credentials
chmod 600 credentials
```

The project-level `credentials` file is gitignored and intended only for local
use.

If one file needs to represent multiple targets, the helper also supports named
profiles. Keep the flat keys for the default target, or define
`PROFILE_<name>__KEY="value"` entries and select them with `SPLUNK_PROFILE`.

Example:

```bash
SPLUNK_PROFILE="cloud"

PROFILE_cloud__SPLUNK_PLATFORM="cloud"
PROFILE_cloud__SPLUNK_TARGET_ROLE="search-tier"
PROFILE_cloud__SPLUNK_SEARCH_API_URI="https://my-stack.stg.splunkcloud.com:8089"
PROFILE_cloud__SPLUNK_CLOUD_STACK="my-stack"
PROFILE_cloud__ACS_SERVER="https://staging.admin.splunk.com"

PROFILE_hf__SPLUNK_PLATFORM="enterprise"
PROFILE_hf__SPLUNK_TARGET_ROLE="heavy-forwarder"
PROFILE_hf__SPLUNK_SEARCH_API_URI="https://hf.example.com:8089"

PROFILE_onprem__SPLUNK_PLATFORM="enterprise"
PROFILE_onprem__SPLUNK_TARGET_ROLE="search-tier"
PROFILE_onprem__SPLUNK_SEARCH_API_URI="https://onprem.example.com:8089"
```

This lets one `credentials` file cover:

- a Splunk Cloud stack/search tier
- a heavy forwarder or intermediate Enterprise node
- a separate on-prem search head or lab deployment

If one workflow needs two targets at once, keep `SPLUNK_PROFILE` on the primary
platform target and set `SPLUNK_SEARCH_PROFILE` for the paired search-tier REST
target.

Example:

```bash
SPLUNK_PROFILE="cloud"
SPLUNK_SEARCH_PROFILE="hf"
SPLUNK_TARGET_ROLE="search-tier"
SPLUNK_SEARCH_TARGET_ROLE="heavy-forwarder"
```

In that mode:

- Cloud keeps `SPLUNK_PLATFORM`, ACS, stack, and token settings
- HF overrides only search-tier REST and SSH settings such as
  `SPLUNK_SEARCH_API_URI`, `SPLUNK_URI`, `SPLUNK_USER`, `SPLUNK_PASS`, and
  `SPLUNK_SSH_*`
- `SPLUNK_TARGET_ROLE` keeps the primary Cloud/search-tier role, while
  `SPLUNK_SEARCH_TARGET_ROLE` documents the paired HF role
- If you want to run forwarder-side REST actions non-interactively, either
  select the HF profile directly or override the run with
  `SPLUNK_PLATFORM=enterprise`

For Enterprise targets, that same file can also include connection and SSH
staging settings:

```bash
SPLUNK_HOST="10.110.253.20"
SPLUNK_MGMT_PORT="8089"
SPLUNK_SEARCH_API_URI="https://10.110.253.20:8089"
# Legacy alias kept for backward compatibility
SPLUNK_URI="${SPLUNK_SEARCH_API_URI}"
SPLUNK_SSH_HOST="10.110.253.20"
SPLUNK_SSH_PORT="22"
SPLUNK_SSH_USER="splunk"
SPLUNK_SSH_PASS=""
```

For Splunk Cloud, the credentials file can also include:

```bash
SPLUNK_SEARCH_API_URI="https://your-stack.splunkcloud.com:8089"
SPLUNK_CLOUD_STACK="your-stack-name"
SPLUNK_CLOUD_SEARCH_HEAD=""
ACS_SERVER="https://admin.splunk.com"
STACK_TOKEN=""
STACK_USERNAME=""
STACK_PASSWORD=""
STACK_TOKEN_USER=""
```

For Splunk Observability Cloud, the credentials file can include the realm and
the local file path containing the Observability API token:

```bash
SPLUNK_O11Y_REALM="us0"
SPLUNK_O11Y_TOKEN_FILE="/tmp/splunk_o11y_api_token"
```

Keep the token value out of `credentials`. Create or update the token file with
`bash skills/shared/scripts/write_secret_file.sh /tmp/splunk_o11y_api_token`,
then pass no token flag when using the Observability dashboard builder or OTel
Collector setup scripts.

`SPLUNK_PLATFORM` is optional. In normal use, scripts infer the target from the
current operation plus your Cloud/REST settings. If one credentials file
contains both Cloud and Enterprise/HF targets, interactive runs will prompt
when a command is ambiguous.

Use `SPLUNK_SEARCH_API_URI="https://<deployment>.splunkcloud.com:8089"` only
when you also need search-tier REST API access for app-specific configuration or
validation. The helper prefers `SPLUNK_SEARCH_API_URI` and falls back to the
legacy alias `SPLUNK_URI`. These values are stored as strings in the
`credentials` file; the helper supports simple `${OTHER_KEY}` references there,
but does not execute arbitrary shell expressions.

### 2. Install Apps Or TAs

The default installation path is **Splunkbase first, local fallback**. Pull
the latest version from Splunkbase:

```bash
bash skills/splunk-app-install/scripts/install_app.sh \
  --source splunkbase \
  --app-id 5580
```

If Splunkbase is unavailable (no credentials, download failure, or a private
app), fall back to a local package in `splunk-ta/`:

```bash
bash skills/splunk-app-install/scripts/install_app.sh \
  --source local \
  --file splunk-ta/my_app.tgz
```

The `splunk-ta/` directory is the local package cache. Splunkbase downloads
are saved there automatically, `--source local` looks there when listing
available packages, and the binaries are intentionally ignored by Git.

Some installs also pull required companion packages from the app registry. For
example, installing Cisco Enterprise Networking (`7539`) now auto-installs the
required Cisco Catalyst Add-on (`7538`) when it is not already present. The
Cisco Catalyst Enhanced Netflow Add-on (`6872`) is optional for additional
dashboard coverage and is no longer auto-installed.

When the target platform is **Splunk Enterprise**, the installer will:

1. install directly from the filesystem when the Splunk host is local
2. stage local packages over SSH for remote hosts
3. install the resulting server-local path through the management API with `filename=true`

When the target platform is **Splunk Cloud**, the installer uses ACS:

1. known Splunkbase-backed apps are installed or updated with ACS Splunkbase commands
2. private apps are vetted and installed with `acs apps install private`
3. restart requirements are checked through `acs status current-stack`

After a successful install or uninstall, the generic app-management scripts
restart Splunk automatically on Enterprise or trigger an ACS restart only when
Splunk Cloud reports `restartRequired=true`. Use `--no-restart` only when
batching multiple changes before a single final restart.

### 3. Run A Skill-Specific Setup

After installation, use the matching setup skill.

Examples:

```text
Set up the Cisco Catalyst TA for my Catalyst Center at 10.100.0.60
```

```text
Set up Cisco ACI for my fabric and show me the dry-run first
```

```text
Set up Nexus 9000 and tell me which TA and dashboards it needs
```

```text
Set up Cisco Duo through Cisco Security Cloud and show me the required inputs first
```

```text
Configure the Cisco Intersight TA for my account
```

```text
Set up Cisco ThousandEyes and show me the dry-run first
```

```text
Install and configure Splunk Stream
```

```text
Prepare Splunk Connect for Syslog and render a Docker deployment
```

```text
Bootstrap a Splunk heavy forwarder on my Linux host and point it at my indexer cluster
```

```text
Render a Splunk Operator for Kubernetes C3 deployment and run preflight
```

```text
Render a Splunk POD medium profile for my Cisco UCS controller and worker nodes
```

The agent is expected to ask only for **non-secret** values in conversation,
such as:

- hostnames
- IP addresses
- account names
- organization IDs
- index names
- regions
- feature toggles

Secrets should come from the `credentials` file or from temporary files passed
to `--password-file`, `--api-token-file`, or similar flags.

For the account-driven Cisco skills, admins can also start with the skill-local
`template.example`, copy it to `template.local`, and use that worksheet to
collect non-secret account details before the actual setup run. Completed
`template.local` files are intended to stay local and out of git.

When using `cisco-product-setup`, start with its dry-run output. It shows the
routed skill, the relevant `template.example`, the missing required
configure-time values, and whether the product is fully automated or only
cataloged as a manual gap or unsupported item.

### 4. Validate The Deployment

Each skill provides a validation script under its own `scripts/` directory.

Examples:

```bash
bash skills/cisco-catalyst-ta-setup/scripts/validate.sh
```

```bash
bash skills/cisco-meraki-ta-setup/scripts/validate.sh
```

```bash
bash skills/splunk-stream-setup/scripts/validate.sh
```

```bash
bash skills/splunk-enterprise-kubernetes-setup/scripts/validate.sh --target sok
```

The validation scripts generally check:

- app installation state
- indexes and macros
- account or input configuration
- data presence in the expected indexes

For rendered Kubernetes or external-collector workflows, validation also checks
that the expected generated files are present and can optionally run live status
commands when the target environment is reachable.

## Splunk Cloud Notes

Splunk Cloud support in this repo follows the documented platform split:

- **ACS-managed actions**: app install, app uninstall, index creation, and
  restarts.
- **Search-tier REST actions**: TA-specific account setup, input enablement,
  macro updates, saved search toggles, KV Store access, and validation.
- **Forwarder-managed actions**: on Splunk Cloud, data inputs still run on
  forwarders or infrastructure under your control. The repo does not attempt to
  turn the cloud search tier into a local collector.

For example, the Cisco TA skills can configure their app objects on the Cloud
search tier over REST once the app is installed, while the generic installer and
index creation logic use ACS.

## Working With Remote Splunk Hosts

To target a remote Splunk instance instead of localhost:

```bash
export SPLUNK_SEARCH_API_URI="https://splunk-host:8089"
```

### SSL Verification

By default, Splunk REST calls keep compatibility mode and skip TLS certificate
verification (`curl -k`) because on-prem Splunk deployments often use
self-signed certificates. To enable strict verification with system trust,
set:

```bash
export SPLUNK_VERIFY_SSL="true"
```

If you need secure verification with a private CA instead of the system trust
store, set:

```bash
export SPLUNK_CA_CERT="/path/to/splunk-ca.pem"
```

Splunkbase uses certificate verification by default. Remote app downloads keep
compatibility with the Splunk TLS setting unless you override them separately
with `APP_DOWNLOAD_VERIFY_SSL`, `APP_DOWNLOAD_CA_CERT`,
`SPLUNKBASE_VERIFY_SSL`, or `SPLUNKBASE_CA_CERT`.

You can also define `SPLUNK_SEARCH_API_URI` in the `credentials` file so you do
not have to export it each session. The helper still accepts `SPLUNK_URI` as a
legacy alias.

Remote workflows matter most in two places:

- **app installation**: Enterprise local files may need SSH staging, while
  Splunk Cloud installs use ACS
- **host bootstrap**: Linux Enterprise host setup can run directly on the
  target host or over SSH using staged packages and remote command execution
- **validation/setup**: all search-tier REST operations must be able to reach
  the remote management port

## Secure Credential Handling

This repo is opinionated about secret handling.

Rules of thumb:

- Do **not** paste passwords, API keys, tokens, or client secrets into chat.
- Do **not** pass secrets directly as shell arguments when a file-based option
  exists.
- Do **not** hardcode secrets in scripts.

Safe patterns used in this repo:

- Splunk credentials live in `credentials` or `~/.splunk/credentials`.
- Splunk auth is sent to the REST API through stdin or helper wrappers rather
  than exposed in process listings.
- Device or vendor secrets should be provided through temporary files.
- Use `skills/shared/scripts/write_secret_file.sh` to create those files without
  putting secret values in shell history.

Example:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/device_secret

bash skills/cisco-catalyst-ta-setup/scripts/configure_account.sh \
  --type catalyst_center \
  --name my_catc \
  --host https://10.100.0.60 \
  --username myuser \
  --password-file /tmp/device_secret

rm -f /tmp/device_secret
```

The repository rule file that defines this behavior is:

```text
rules/credential-handling.mdc
```

## Contributing

Before opening a pull request, read `CONTRIBUTING.md` and run the checks listed
there. At minimum, changes should pass the Python tests, Bats tests, ShellCheck,
Ruff, YAML linting, generated-doc freshness checks, and repo-readiness checks.

Security issues and leaked secrets should not be reported through public issues.
Use the process in `SECURITY.md`.

## Repository Layout

```text
splunk-cisco-skills/
├── .github/
│   ├── workflows/
│   │   └── ci.yml              # shell, Python, lint, and generated-doc checks
│   ├── ISSUE_TEMPLATE/         # bug and skill request templates
│   ├── CODEOWNERS
│   └── pull_request_template.md
├── README.md
├── AGENTS.md                    # Codex project context
├── CLAUDE.md                    # Claude Code project context
├── CONTRIBUTING.md
├── SECURITY.md
├── CHANGELOG.md
├── LICENSE
├── ARCHITECTURE.md
├── CLOUD_DEPLOYMENT_MATRIX.md
├── DEPLOYMENT_ROLE_MATRIX.md
├── DEMO_SCRIPTS.md
├── credentials.example
├── credentials                  # local only, gitignored
├── requirements-agent.txt       # local MCP agent server dependencies
├── requirements-dev.txt         # test and lint dependencies
├── pytest.ini
├── .shellcheckrc
├── .yamllint.yml
├── .gitattributes
├── .mcp.json                    # Claude Code MCP server config
├── .cursor/
│   ├── mcp.json                # Cursor MCP server config
│   └── skills/                 # Cursor skill symlinks (one per skill)
├── .claude/
│   ├── commands/               # Claude Code slash commands (one per skill)
│   └── rules/
│       └── credential-handling.md
├── agent/
│   ├── register-codex-splunk-cisco-skills-mcp.sh
│   ├── run-splunk-cisco-skills-mcp.py
│   └── splunk_cisco_skills_mcp/
│       ├── core.py
│       └── server.py
├── splunk-ta/                   # local package cache; binaries ignored by git
│   └── _unpacked/              # review-only extracted copies
├── splunk-mcp-rendered/
│   └── run-splunk-mcp.js        # tracked bridge for Splunk MCP Server
├── sc4s-rendered/               # local generated SC4S output, gitignored
├── sc4snmp-rendered/            # local generated SC4SNMP output, gitignored
├── splunk-*-rendered/            # local generated platform and OTel output, gitignored
├── ta-for-indexers-rendered/     # local generated ES indexer bundle, gitignored
├── skills/
│   ├── shared/
│   │   ├── app_registry.json   # single source of truth for Splunkbase IDs
│   │   ├── lib/
│   │   │   ├── credential_helpers.sh    # shim that sources all modules
│   │   │   ├── credentials.sh           # profile resolution and loading
│   │   │   ├── rest_helpers.sh          # Splunk REST API wrappers
│   │   │   ├── acs_helpers.sh           # ACS CLI wrappers
│   │   │   ├── splunkbase_helpers.sh    # Splunkbase auth and downloads
│   │   │   ├── host_bootstrap_helpers.sh # SSH/bootstrap helper functions
│   │   │   ├── configure_account_helpers.sh  # create-or-update pattern
│   │   │   ├── cluster_helpers.sh       # indexer-cluster helper functions
│   │   │   ├── license_helpers.sh       # Enterprise licensing helpers
│   │   │   ├── edge_processor_helpers.sh # Edge Processor render helpers
│   │   │   ├── deployment_helpers.sh    # rendered deployment helpers
│   │   │   ├── registry_helpers.sh      # app registry and role lookups
│   │   │   ├── soar_helpers.sh          # SOAR install and handoff helpers
│   │   │   └── yaml_compat.py           # stdlib YAML parser for PyYAML-free hosts
│   │   └── scripts/
│   │       ├── setup_credentials.sh
│   │       ├── write_secret_file.sh
│   │       ├── cloud_batch_install.sh
│   │       ├── cloud_batch_uninstall.sh
│   │       ├── generate_deployment_docs.py   # refresh DEPLOYMENT_ROLE_MATRIX.md + CLOUD_DEPLOYMENT_MATRIX.md
│   │       ├── generate_skill_ux_catalog.py  # refresh SKILL_UX_CATALOG.md
│   │       ├── smoke_sc4x_live.sh            # SC4S/SC4SNMP live smoke test
│   │       └── test_splunkbase_connection.sh # Splunkbase credential check
│   ├── cisco-appdynamics-setup/
│   ├── cisco-catalyst-enhanced-netflow-setup/
│   ├── cisco-catalyst-ta-setup/
│   ├── cisco-dc-networking-setup/
│   ├── cisco-enterprise-networking-setup/
│   ├── cisco-intersight-setup/
│   ├── cisco-isovalent-platform-setup/
│   ├── cisco-meraki-ta-setup/
│   ├── cisco-product-setup/
│   ├── cisco-scan-setup/
│   ├── cisco-secure-access-setup/
│   ├── cisco-secure-email-web-gateway-setup/
│   ├── cisco-security-cloud-setup/
│   ├── cisco-spaces-setup/
│   ├── cisco-talos-intelligence-setup/
│   ├── cisco-thousandeyes-mcp-setup/
│   ├── cisco-thousandeyes-setup/
│   ├── cisco-ucs-ta-setup/
│   ├── cisco-webex-setup/
│   ├── splunk-admin-doctor/
│   ├── splunk-agent-management-setup/
│   ├── splunk-ai-assistant-setup/
│   ├── splunk-app-install/
│   ├── splunk-asset-risk-intelligence-setup/
│   ├── splunk-attack-analyzer-setup/
│   ├── splunk-cloud-acs-allowlist-setup/
│   ├── splunk-cloud-data-manager-setup/
│   ├── splunk-connect-for-otlp-setup/
│   ├── splunk-connect-for-snmp-setup/
│   ├── splunk-connect-for-syslog-setup/
│   ├── splunk-edge-processor-setup/
│   ├── splunk-enterprise-host-setup/
│   ├── splunk-enterprise-kubernetes-setup/
│   ├── splunk-enterprise-public-exposure-hardening/
│   ├── splunk-enterprise-security-config/
│   ├── splunk-enterprise-security-install/
│   ├── splunk-federated-search-setup/
│   ├── splunk-hec-service-setup/
│   ├── splunk-platform-restart-orchestrator/
│   ├── splunk-index-lifecycle-smartstore-setup/
│   ├── splunk-indexer-cluster-setup/
│   ├── splunk-itsi-config/
│   ├── splunk-itsi-setup/
│   ├── splunk-license-manager-setup/
│   ├── splunk-mcp-server-setup/
│   ├── splunk-monitoring-console-setup/
│   ├── splunk-observability-ai-agent-monitoring-setup/
│   ├── splunk-observability-aws-integration/
│   ├── splunk-observability-cisco-ai-pod-integration/
│   ├── splunk-observability-cisco-intersight-integration/
│   ├── splunk-observability-cisco-nexus-integration/
│   ├── splunk-observability-cloud-integration-setup/
│   ├── splunk-observability-dashboard-builder/
│   ├── splunk-observability-database-monitoring-setup/
│   ├── splunk-observability-isovalent-integration/
│   ├── splunk-observability-k8s-auto-instrumentation-setup/
│   ├── splunk-observability-k8s-frontend-rum-setup/
│   ├── splunk-observability-native-ops/
│   ├── splunk-observability-nvidia-gpu-integration/
│   ├── splunk-observability-otel-collector-setup/
│   ├── splunk-observability-thousandeyes-integration/
│   ├── splunk-oncall-setup/
│   ├── splunk-platform-pki-setup/
│   ├── splunk-security-essentials-setup/
│   ├── splunk-security-portfolio-setup/
│   ├── splunk-soar-setup/
│   ├── splunk-stream-setup/
│   ├── splunk-uba-setup/
│   ├── splunk-universal-forwarder-setup/
│   └── splunk-workload-management-setup/
├── tests/                       # bats and Python test suites
└── rules/
    └── credential-handling.mdc
```

## What To Read For Detail

If you want to understand a specific skill, read these files in order:

1. `skills/<skill>/SKILL.md`
2. `skills/<skill>/reference.md` if present
3. `skills/<skill>/scripts/*.sh`

That is where the real behavior lives.

## Local MCP Agent Server

The repo includes a local MCP server, `splunk-cisco-skills`, for agent clients
that can use MCP tools. It exposes the skill catalog, skill instructions,
templates, Cisco product resolution, dry-run planning, and gated script
execution.

The launcher invoked by Claude Code, Cursor, and Codex prefers the repo-local
`.venv` when it exists, so GUI clients do not need to inherit an activated
shell. The simplest setup is:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-agent.txt
```

If you prefer a system-wide install:

```bash
pip3 install -r requirements-agent.txt
```

If your global pip configuration points at an internal package index that does
not mirror the MCP SDK, install from public PyPI explicitly:

```bash
pip install --index-url https://pypi.org/simple -r requirements-agent.txt
```

The server is registered in `.mcp.json` for Claude Code and `.cursor/mcp.json`
for Cursor alongside the existing `splunk-mcp` bridge. Codex stores MCP servers
in the user config, so register the repo-local server once with:

```bash
bash agent/register-codex-splunk-cisco-skills-mcp.sh
```

Read-only plans include help output, validation/list scripts, Cisco product
dry-runs/lists, and allowlisted render/preflight/status/validate/dry-run
previews. They can run with explicit client confirmation. Plans are single-use:
each plan hash is consumed when it executes, and plan hashes expire after one
hour by default (`MCP_PLAN_TTL_SECONDS`; set `0` to disable expiry). To allow
mutating setup, install, or configure scripts, start the MCP server process with:

```bash
SPLUNK_SKILLS_MCP_ALLOW_MUTATION=1
```

Execution always requires a previously generated plan hash and explicit
confirmation from the client. Each `plan_*` call accepts a `timeout_seconds`
argument (default 30 minutes, capped at 2 hours by default or by
`MCP_MAX_TIMEOUT_SECONDS`); `execute_*` uses the timeout stored in the matching
plan. If a child process exceeds that timeout, the server sends SIGTERM, then
SIGKILL after a short grace, and the response includes `timed_out: true`.
Subprocess stdout and stderr are bounded per stream (256 KiB each) to keep the
server stable when scripts are noisy.

## Requirements

Minimum expected environment:

- `bash`
- `curl`
- `python3`
- `pip install -r requirements-agent.txt` for the local MCP agent server
- Cursor, Codex, or Claude Code if you want the agent-driven workflow
- Splunk Enterprise with REST API access on `8089`, or Splunk Cloud with ACS
  access and optional search-tier REST API access on `8089`, for app and TA
  workflows
- a `splunk.com` account for Splunkbase downloads when installing public apps

For the per-skill software and live-access matrix, see
[`SKILL_REQUIREMENTS.md`](SKILL_REQUIREMENTS.md). It calls out workflow-specific
tools such as `kubectl`, `helm`, `yq`, `node`, `mcp-remote`, Docker/Podman,
Terraform, cloud CLIs, and `splunk-rum` only where those skills need them.

For Splunk Cloud workflows, you should also install the ACS CLI:

```bash
brew install acs
```

Depending on the workflow, you may also need:

- SSH access to the target Splunk host for remote local-package installs
- `sshpass` for password-based remote host bootstrap and package staging
- vendor credentials or tokens supplied through files for account setup scripts
- `search-api` allow-list access for Cloud search-tier REST operations
- `kubectl` and `helm` for Splunk Operator for Kubernetes workflows
- `aws` CLI access when rendering the optional EKS kubeconfig helper
- the Splunk Kubernetes Installer on the bastion host for Splunk POD workflows

Render-only Kubernetes runs need only local shell and Python. Preflight, apply,
and live validation phases need access to the Kubernetes cluster or POD bastion
that will run the generated assets.

## Current Scope

This repo focuses on vendor TAs/apps, Splunk administration workflows, and
customer-managed collection or integration runtimes that can be configured
through REST, shell automation, rendered assets, or explicit handoffs on
**self-managed Splunk Enterprise** and on **Splunk Cloud search tiers with ACS
plus allowlisted REST API access**.

The platform administration skills deliberately separate self-managed
Enterprise file-render workflows from Splunk Cloud managed features:
`splunk-federated-search-setup` renders Splunk-to-Splunk `federated.conf` and
standard-mode `indexes.conf` assets, while Splunk Cloud-only Federated Search
for Amazon S3 remains a supported Cloud UI/API workflow outside this renderer.
`splunk-index-lifecycle-smartstore-setup` targets self-managed indexers and
cluster managers with `indexes.conf`, `server.conf`, and `limits.conf`; Splunk
Cloud SmartStore/storage lifecycle is managed by Splunk.
`splunk-monitoring-console-setup` targets self-managed Enterprise Monitoring
Console configuration and renders `distsearch.conf` only for peer and
search-group review because search peer trust and passwords must be handled
through Splunk Web or an operator-controlled secure workflow.
`splunk-license-manager-setup` and `splunk-indexer-cluster-setup` target
self-managed Enterprise control planes; Splunk Cloud licensing and indexer
clusters remain Splunk-managed. `splunk-cloud-acs-allowlist-setup` is the
Cloud-side control-plane workflow for ACS feature allowlists and does not map
to an Enterprise runtime role.
`splunk-admin-doctor` spans both Splunk Cloud and Splunk Enterprise as a
diagnostic router: it renders reports, fix plans, and handoffs, but only applies
the narrow safe fix packets exposed by its workflow.
`splunk-cloud-data-manager-setup` stays Cloud-side and artifact-driven: it
renders artifacts, runs doctor checks, validates, and safely applies supported
Data Manager-generated AWS, Azure, GCP, and CrowdStrike onboarding artifacts
without claiming private Data Manager API coverage.

The biggest Cloud-specific limitation is hybrid collection architectures. For
example, Splunk Stream on Splunk Cloud uses a cloud-hosted `splunk_app_stream`
plus forwarders you control; this repo therefore treats Stream as a special
case rather than a pure single-target install. `splunk-connect-for-syslog-setup`
follows a similar principle for SC4S: the repo prepares Splunk and renders the
collector runtime assets, but the SC4S syslog-ng container itself runs on
customer-managed infrastructure rather than on the Cloud search tier.
`splunk-connect-for-snmp-setup` follows the same external-collector model for
SC4SNMP polling and traps. `splunk-connect-for-otlp-setup` follows the hybrid
OTLP modular-input model: it can configure the Splunk Platform app where the
listener can actually be reached, but Splunk Cloud Classic needs IDM or a
customer-managed heavy forwarder, and Splunk Cloud Victoria still requires
topology and inbound reachability validation before direct listener placement.
`splunk-edge-processor-setup` also follows a customer-managed runtime model: it
renders Edge Processor instance and pipeline assets that join to a Splunk Cloud
tenant or Splunk Enterprise data management node, and emits ACS allowlist
handoffs when Cloud destinations need them.
`splunk-observability-otel-collector-setup` extends that pattern to
customer-managed Kubernetes or Linux OpenTelemetry Collector runtimes that send
data to Splunk Observability Cloud and optional Splunk Platform HEC. In these
workflows, the rendered apply paths are rerunnable install-or-upgrade
entrypoints for customer-managed runtimes.
`splunk-observability-database-monitoring-setup` layers database receiver
configuration for PostgreSQL, Microsoft SQL Server, and Oracle Database onto
that collector model. `splunk-observability-ai-agent-monitoring-setup` renders
GenAI instrumentation, evaluation telemetry, histogram collector readiness, and
AI Infrastructure Monitoring handoffs. `splunk-observability-aws-integration`
is an Observability Cloud API and IaC workflow for AWSCloudWatch polling and
Metric Streams, not an AWS log-ingestion path.
`splunk-observability-dashboard-builder` is separate from runtime placement: it
renders and validates native Observability Cloud dashboard API payloads and can
apply them only when explicitly requested.
`splunk-observability-native-ops` follows the same no-runtime-placement model
for native Observability operations: it renders supported API payloads, API
validation requests, deeplinks, and deterministic operator handoffs for UI-only
surfaces. The Observability integration skills
(`splunk-observability-cloud-integration-setup`,
`splunk-observability-ai-agent-monitoring-setup`,
`splunk-observability-database-monitoring-setup`,
`splunk-observability-k8s-auto-instrumentation-setup`,
`splunk-observability-k8s-frontend-rum-setup`,
`splunk-observability-aws-integration`,
`splunk-observability-thousandeyes-integration`,
`splunk-observability-isovalent-integration`,
`splunk-observability-cisco-nexus-integration`,
`splunk-observability-cisco-intersight-integration`,
`splunk-observability-nvidia-gpu-integration`, and
`splunk-observability-cisco-ai-pod-integration`) follow the same render-first
pattern: collector-dependent skills overlay the base Splunk OTel Collector
chart from `splunk-observability-otel-collector-setup`; platform-pairing and
cloud-service skills render API, IaC, or operator handoff payloads; and the
skills hand off dashboards and detectors to
`splunk-observability-dashboard-builder` and `splunk-observability-native-ops`
where relevant.
`splunk-enterprise-kubernetes-setup` is for self-managed Splunk Enterprise on
Kubernetes: either Splunk Operator for Kubernetes on an existing cluster, or
Splunk POD on Cisco UCS with the Splunk Kubernetes Installer.
`cisco-isovalent-platform-setup` installs the Isovalent platform itself
(Cilium, Tetragon, optional Hubble Enterprise) on Kubernetes; it is explicitly
not a Splunk TA installer and is the prerequisite for wiring Isovalent
telemetry into Splunk Platform + Splunk Observability Cloud via
`splunk-observability-isovalent-integration`.
`cisco-thousandeyes-mcp-setup` renders Model Context Protocol client
configurations for Cursor, Claude Code, Codex, VS Code, and AWS Kiro; the
MCP server itself is operated by Cisco.
`splunk-platform-pki-setup` is a self-managed Splunk Enterprise platform PKI
workflow. It mints per-component certificates, renders FIPS wiring and TLS
algorithm presets, and hands off rolling restart / cluster bundle apply to
`splunk-indexer-cluster-setup`. Splunk Cloud platform certificates remain
Splunk-managed.
