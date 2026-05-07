# Cloud Deployment Matrix

_Generated from `skills/shared/app_registry.json` by `skills/shared/scripts/generate_deployment_docs.py`; do not edit manually._

This document defines the normal Splunk Cloud deployment model for the
repo's cloud-supported apps and workflows.

For cross-platform placement across search tiers, indexers, forwarders, and
external collectors, see
[`DEPLOYMENT_ROLE_MATRIX.md`](DEPLOYMENT_ROLE_MATRIX.md).

## Default Rule

- For apps published on Splunkbase, prefer **ACS Splunkbase installs** and let
  ACS fetch the latest compatible release. Use `--source splunkbase` with the
  app's Splunkbase ID.
- Use private package uploads (`acs apps install private`) only for genuinely
  private or pre-vetted apps that do not have a public Splunkbase listing.
- Keep vendor archives in `splunk-ta/` as the local cache and review copy.
- Use **ACS** for Splunk Cloud app installation, index management, and restarts.
- Use **search-tier REST** for post-install app configuration when the
  `search-api` allow list permits it.
- Do **not** require extract/repack as part of the normal workflow.
- Treat anything under `splunk-ta/_unpacked/` as review-only.

## App And Workflow Matrix

| Skill | Splunkbase ID | Cloud install path | Cloud config path | Notes |
| --- | --- | --- | --- | --- |
| `cisco-catalyst-ta-setup` | 7538 | ACS Splunkbase | REST via custom account/input handlers | Cisco EULA license-ack required. |
| `cisco-catalyst-enhanced-netflow-setup` | 6872 | Manual install on HF/UF you control | No app-local config; validate the NetFlow/IPFIX receiver path on the same target | Cisco EULA license-ack required. Optional forwarder-side mappings for extra Enterprise Networking NetFlow dashboards. |
| `cisco-appdynamics-setup` | 3471 | ACS Splunkbase | REST via custom account/input handlers | Configure the AppDynamics controller account and data inputs after install. |
| `cisco-security-cloud-setup` | 7404 | ACS Splunkbase | REST via CiscoSecurityCloud custom admin handlers | Cisco EULA license-ack required. Multi-product Cisco Security integration app with product-specific setup flows for each packaged integration. |
| `cisco-secure-access-setup` | 5558 | ACS Splunkbase | REST via `org_accounts`, `update_settings`, and related app APIs | Cisco EULA license-ack required. Secure Access automation installs both the event add-on and dashboard app, then covers org onboarding plus dashboard settings/bootstrap. |
| `cisco-secure-access-setup` add-on | 7569 | ACS Splunkbase | Add-on event inputs and log-index settings | Cisco EULA license-ack required. Required companion add-on for Secure Access, Umbrella, and Cloudlock event-log ingestion. |
| `cisco-webex-setup` Webex add-on | 8365 | ACS Splunkbase | REST via Webex add-on account/input handlers for OAuth accounts and Webex REST API inputs | Installs with the companion Webex App dashboards. Covers meetings, admin/security audit, meeting quality, detailed call history, generic endpoint, and Contact Center Search inputs. |
| `cisco-webex-setup` Webex app | 4992 | ACS Splunkbase | Search-tier macro alignment for wx, wxc, and wxcc dashboard indexes | Companion dashboard app for the Webex Add-on. Provides Webex Meetings, Calling, Contact Center, Security, and data-quality dashboards. |
| `cisco-ucs-ta-setup` | 2731 | ACS Splunkbase | REST via UCS server, template, and cisco_ucs_task handlers | Creates the cisco_ucs index, configures UCS Manager server records with encrypted passwords, default/custom class-ID templates, and cisco:ucs inputs. |
| `cisco-secure-email-web-gateway-setup` ESA | 1761 | ACS Splunkbase | Search-tier/indexer parser package plus email index and Cisco_ESA_Index macro alignment | Parser/search-time add-on. Collection is SC4S or file monitor; this repo prepares Splunk-side package placement, indexes, macros, and handoff snippets. |
| `cisco-secure-email-web-gateway-setup` WSA | 1747 | ACS Splunkbase | Search-tier/indexer parser package plus netproxy index and Cisco_WSA_Index macro alignment | Parser/search-time add-on. Collection is SC4S or file monitor; this repo prepares Splunk-side package placement, indexes, macros, and handoff snippets. |
| `cisco-talos-intelligence-setup` | 7557 | ACS Splunkbase for supported ES Cloud stacks | Validate ES Cloud support posture, service-account fingerprint, get_talos_enrichment capability, alert actions, and threatlist state | Enterprise Security Cloud-first integration. Service account certificate/private key is normally Splunk Cloud-provisioned and remains file-based for diagnostics only. |
| `cisco-meraki-ta-setup` | 5580 | ACS Splunkbase | REST via custom account/input handlers | Cisco EULA license-ack required. Dashboard macro alignment after install. |
| `cisco-intersight-setup` | 7828 | ACS Splunkbase | REST via custom account/input handlers | Cisco EULA license-ack required. Index creation uses ACS. |
| `cisco-dc-networking-setup` | 7777 | ACS Splunkbase | REST via custom account/input handlers | Cisco EULA license-ack required. Index creation uses ACS. |
| `cisco-enterprise-networking-setup` | 7539 | ACS Splunkbase | REST for macros/saved searches/datamodel settings | Cisco EULA license-ack required. Visualization app only; installer auto-adds required TA `7538` when missing. Optional Enhanced Netflow add-on `6872` should be offered separately when users want extra NetFlow dashboards. |
| `cisco-product-setup` | N/A | Delegates to the routed Cisco app install path for the resolved product | Delegates to the routed Cisco setup skill after resolving the SCAN catalog product name | Top-level Cisco product orchestrator. Uses the packaged SCAN catalog plus local overrides to resolve a product name, classify gaps, and run the matching setup workflow. |
| `cisco-scan-setup` | 8566 | ACS Splunkbase | Search-tier REST validation and optional S3 catalog sync | Cisco EULA license-ack required. Search-head-only catalog app; no data inputs, indexes, or forwarder deployment. |
| `cisco-thousandeyes-setup` | 7719 | ACS Splunkbase | REST for OAuth account, HEC-based streaming inputs, polling inputs | Requires HEC token. OAuth device code flow for auth. ITSI integration optional. |
| `splunk-itsi-setup` | 1841 | ACS Splunkbase | No post-install REST config needed | Premium product; requires ITSI license. Enables ThousandEyes ITSI integration. |
| `splunk-itsi-config` content library | 5391 | ACS Splunkbase or Splunk Support / Cloud App Request | Content pack catalog refresh, preview, install, and validate through ITSI REST workflows | Requires ITSI app 1841. Used by splunk-itsi-config for supported content-pack workflows. |
| `splunk-enterprise-security-install` | 263 | Splunk Support coordinated ES service workflow | `splunk-enterprise-security-config` validation plus Splunk Support for Cloud-managed indexer-side changes | Premium SIEM product. On-prem installs prefer the local ES package when present, fall back to Splunkbase app 263, then run essinstall. |
| `splunk-enterprise-security-config` | N/A | No additional app install; requires ES already provisioned | REST validation and supported search-tier settings; Splunk Cloud indexer-side changes remain support-managed | Operational ES configuration workflow for indexes, roles, CIM data models, enrichment, detections, risk, and validation. |
| `splunk-security-portfolio-setup` | N/A | Delegates to the routed Splunk security product install path for the resolved product | Delegates to the routed setup, config, or explicit handoff workflow after resolving the security product catalog entry | Top-level Splunk security product router/audit workflow covering Enterprise Security, Security Essentials, SOAR, UBA, Attack Analyzer, Asset and Risk Intelligence, and associated security offerings. |
| `splunk-security-essentials-setup` | 3435 | ACS Splunkbase | Search-tier validation plus product UI checklist for Data Inventory Introspection, Content Mapping, app configuration, and optional posture dashboards | Search-head-only app. Safe to install alongside Enterprise Security and has no indexer impact. |
| `splunk-asset-risk-intelligence-setup` | 7180 | ACS Splunkbase or Cloud app request for restricted entitlement; local package fallback when provided | ACS/REST index readiness for ari_staging, ari_asset, ari_internal, and ari_ta plus KV Store, roles/capabilities, post-install configuration, data source, metric, response/audit, investigation, ES integration, Add-on, Echo, upgrade, and uninstall-prerequisite handoffs | Restricted Asset and Risk Intelligence app. Normal ES integration covers asset/identity sync and risk factors; ES 8.5+ Exposure Analytics routes to splunk-enterprise-security-config with ARI Asset/IP/Mac/User discovery sources only. |
| `splunk-asset-risk-intelligence-setup` Windows TA handoff | 7214 | Cloud app request or Splunkbase app 7214 for indexer-side package placement; Universal Forwarder deployment remains customer-managed | Validate ari_ta index readiness and hand off local inputs.conf deployment plus ARI data source activation for Asset, Software, and optional Encryption sources | ARI Technical Add-on for Windows endpoint discovery. Deploy to indexers without local config and to Universal Forwarders with local inputs.conf. |
| `splunk-asset-risk-intelligence-setup` Linux TA handoff | 7416 | Cloud app request or Splunkbase app 7416 for indexer-side package placement; Universal Forwarder deployment remains customer-managed | Validate ari_ta index readiness and hand off local inputs.conf deployment plus ARI data source activation for Asset and optional Encryption sources | ARI Technical Add-on for Linux endpoint discovery. Deploy to indexers without local config and to Universal Forwarders with local inputs.conf. |
| `splunk-asset-risk-intelligence-setup` macOS TA handoff | 7417 | Cloud app request or Splunkbase app 7417 for indexer-side package placement; Universal Forwarder deployment remains customer-managed | Validate ari_ta index readiness and hand off local inputs.conf deployment plus ARI data source activation for Asset, Software, and optional Encryption sources | ARI Technical Add-on for macOS endpoint discovery. Deploy to indexers without local config and to Universal Forwarders with local inputs.conf. |
| `splunk-attack-analyzer-setup` add-on | 6999 | ACS Splunkbase or local package | Create/validate saa index and configure tenant/input settings through supported add-on UI or handoff using file-based API key material | Splunk Add-on for Splunk Attack Analyzer. The setup workflow installs it with the companion dashboard app by default. |
| `splunk-attack-analyzer-setup` app | 7000 | ACS Splunkbase or local package | Search-tier macro validation for saa_indexes and dashboard readiness | Splunk App for Splunk Attack Analyzer. The setup workflow defaults saa_indexes to index=saa. |
| `splunk-soar-setup` | 6361 | ACS Splunkbase | Configure SOAR service connections in the app UI using file-based auth material; Enterprise distributed deployments also require indexer-side placement | Splunk App for SOAR imports SOAR data and remote-search capabilities into the Splunk platform; it does not install a SOAR server. |
| `splunk-soar-setup` export app | 3411 | ACS Splunkbase or Cloud support workflow | Configure Splunk platform to SOAR server export settings, role alignment, TLS trust, and retry behavior | Splunk App for SOAR Export is optional and used when Splunk platform data flows to SOAR. |
| `splunk-uba-setup` Kafka app | 4147 | ACS Splunkbase or local package when still required by an existing UBA deployment | Readiness validation only; standalone UBA server lifecycle remains a manual/professional-services handoff | Optional legacy UBA Kafka ingestion app. New UEBA work should route to Enterprise Security Premier UEBA. |
| `splunk-enterprise-security-config` content update | 3449 | ACS Splunkbase or ES Cloud managed content workflow | Configured through the ES content library workflow for ESCU subscription, story/detection enablement, and content-pack toggles | Splunk ES Content Update is registered under ES configuration, not as a separate security product skill. |
| `splunk-ai-assistant-setup` | 7245 | ACS Splunkbase | App-local Context, Model Runtime, and feature settings happen in the app UI | Search-tier app only. Splunk Cloud installs stay on the public Splunkbase path; Enterprise uses cloud-connected activation after install. Latest verified Splunkbase release is 2.0.0; Agent Mode is Cloud-region gated and FedRAMP IL2 support is limited. |
| `splunk-mcp-server-setup` | N/A | ACS private app upload or vetted local package | REST for mcp.conf settings, token policy, and rate limits; local JSON policy overlays remain package-content concerns | Search-tier MCP endpoint for Splunk with encrypted token issuance and shared Cursor/Codex/Claude Code bridge rendering. |
| `splunk-agent-management-setup` | N/A | Not a Splunk Cloud install path; renders customer-managed Agent Management assets | Rendered serverclass.conf, deployment apps, and deploymentclient.conf for Enterprise deployment-server style workflows | Splunk Enterprise 10.x Agent Management workflow for full Enterprise instances, forwarders, and OTel fleet overview. |
| `splunk-universal-forwarder-setup` | N/A | No Splunk Cloud app install; customer-managed UF runtime forwards to Splunk Enterprise or Splunk Cloud | Local/SSH UF install and enrollment, rendered Windows MSI bootstrap, or Splunk Cloud Universal Forwarder credentials package install | Runtime bootstrap workflow for Universal Forwarders. Server classes and deployment apps remain delegated to splunk-agent-management-setup. |
| `splunk-workload-management-setup` | N/A | Not a Splunk Cloud install path; configures self-managed Enterprise Workload Management | Rendered workload_pools.conf, workload_rules.conf, workload_policy.conf, and local reload helpers | Linux-only Enterprise workflow for cgroups-backed workload pools, workload rules, and admission-rule guardrails. |
| `splunk-hec-service-setup` | N/A | No Splunk Cloud app install; Splunk Cloud HEC tokens are managed through ACS | Enterprise inputs.conf rendering or Splunk Cloud ACS HEC token payloads and helper commands | Reusable HEC platform service workflow for allowed indexes, default source/sourcetype, TLS, and ACK-aware token handling. |
| `splunk-platform-restart-orchestrator` | N/A | No Splunk Cloud app install; plans and executes ACS restarts only when restartRequired=true | Topology-aware restart/reload planning for Splunk Cloud ACS, Enterprise systemd/CLI paths, deployment-server reloads, SHC rolling restart, and indexer-cluster handoffs | Repo-wide restart guardrail workflow. Audits restart call sites, avoids default REST restarts on systemd hosts, and renders handoffs when no safe noninteractive restart path exists. |
| `splunk-connect-for-otlp-setup` | 8704 | ACS Splunkbase for supported Cloud topologies; customer-managed heavy forwarder fallback when inbound OTLP reachability is not proven | REST modular input configuration plus HEC token handoff through splunk-hec-service-setup | Hybrid-gated OTLP modular input. Victoria direct execution requires topology and inbound reachability validation; Classic routes input execution to IDM or customer-managed heavy forwarder. External collectors and SDKs are senders/clients only. |
| `splunk-admin-doctor` | N/A | No Splunk Cloud app install; diagnoses Splunk Cloud and Enterprise admin posture from evidence and safe local probes | Rendered doctor, fix-plan, coverage, handoff, and support-ticket packets; Cloud mutations remain delegated to ACS-capable skills | Full-coverage admin doctor for Cloud and self-managed Enterprise. Classifies every major admin domain as direct local guidance, delegated fix, manual/support path, diagnose-only, or not applicable. |
| `splunk-cloud-data-manager-setup` | N/A | No Splunk Cloud app install; Data Manager is a native Splunk Cloud Platform onboarding experience for cloud-service data | Render-first readiness, doctor, validation, and supported artifact apply workflow for Data Manager AWS CloudFormation/StackSets, Azure ARM, GCP Terraform templates, CrowdStrike FDR handoffs, HEC/index checks, health searches, and provider prerequisite guardrails | Covers AWS, Azure, GCP, and CrowdStrike Data Manager onboarding without claiming private Data Manager APIs or Terraform CRUD for Data Manager inputs. Input creation remains a Data Manager UI handoff; splunk/scp Terraform is adjacent only for supported prerequisites such as indexes, HEC tokens, roles, and allowlists. |
| `splunk-federated-search-setup` | N/A | No Splunk Cloud app install; Federated Search is native platform configuration on the Federated Search Head | REST apply path (`apply-rest.sh`) targets Splunk Cloud `/services/data/federated/{provider,index,settings/general}` directly; Splunk Cloud cannot edit federated.conf, so `aws_s3` providers are rendered as REST payloads with AWS Glue/S3/KMS prerequisites docs; admin user must hold `admin_all_objects` | Complete Federated Search product surface: FSS2S (`type=splunk`) standard or transparent mode with multi-provider/multi-index render, FSS3 (`type=aws_s3`, Splunk Cloud only) REST payloads, file-based and REST apply paths, global federated-search enable/disable, SHC `conf_replication_include.indexes` deployer asset, and live `connectivityStatus` probe. |
| `splunk-index-lifecycle-smartstore-setup` | N/A | Not a Splunk Cloud install path; SmartStore is managed by Splunk Cloud | Rendered self-managed Enterprise SmartStore indexes.conf, server.conf, and limits.conf assets for indexers or cluster managers | Self-managed index lifecycle workflow for remote volumes, retention limits, cache manager settings, remote-storage localization limits, and cluster bundle apply. |
| `splunk-monitoring-console-setup` | N/A | Not a Splunk Cloud app install; Cloud Monitoring Console is Splunk-managed | Rendered self-managed Enterprise Monitoring Console local configuration plus review-only distsearch.conf peer and group helpers | Distributed or standalone Monitoring Console workflow for auto-config, distributed search groups, forwarder monitoring, and platform alert enablement. |
| `splunk-stream-setup` search-tier app | 1809 | ACS or Splunk Cloud support workflow | Stream UI / REST on search tier | Cloud deployment is hybrid, not single-target. |
| `splunk-stream-setup` wire-data add-on | 5234 | ACS or bundled with Stream deployment | No special post-install config in normal flow | Knowledge-object support for Stream search content. |
| `splunk-stream-setup` forwarder add-on | 5238 | Manual install on HF/UF you control | Local HF files plus host forwarding config | This package runs on the heavy/universal forwarder, not the Cloud search tier. |
| `splunk-connect-for-syslog-setup` | N/A | No Splunk Cloud app install; SC4S runtime is rendered for customer-managed hosts or Kubernetes | ACS for indexes/HEC where available, search-tier REST for validation, rendered host/Helm assets for runtime | External syslog-ng collector pattern. Modeled as a workflow row rather than a Splunk app package. |
| `splunk-connect-for-snmp-setup` | N/A | No Splunk Cloud app install; SC4SNMP runtime is rendered for customer-managed Docker Compose or Kubernetes | ACS for indexes/HEC where available, search-tier REST for validation, rendered compose/Helm assets for runtime | External SNMP collector pattern. Modeled as a workflow row rather than a Splunk app package. |
| `splunk-observability-otel-collector-setup` | N/A | No Splunk Cloud app install; OTel Collector runtime is rendered for customer-managed Kubernetes clusters or Linux hosts | Rendered Helm values, Kubernetes secret helpers, Linux installer wrappers, and optional HEC token handoff scripts using file-based tokens | External OpenTelemetry Collector workflow for Observability metrics, traces, profiling, Kubernetes events, discovery, auto-instrumentation, and optional Splunk Platform HEC logs with splunk-hec-service-setup handoff helpers. |
| `splunk-observability-ai-agent-monitoring-setup` | N/A | No Splunk Cloud app install; AI Agent Monitoring uses customer-managed Python instrumentation, the Splunk OTel Collector, Splunk Platform HEC, and Log Observer Connect prerequisites | Rendered GenAI package/runtime env plans, histogram collector overlays, HEC and Log Observer Connect handoffs, dashboard/detector specs, and an explicit coverage report for every AI Agent Monitoring and AI Infrastructure Monitoring surface | Render-first orchestration skill for Splunk AI Agent Monitoring. Delegates collector apply to splunk-observability-otel-collector-setup, HEC apply to splunk-hec-service-setup, LOC apply to splunk-observability-cloud-integration-setup, dashboards to splunk-observability-dashboard-builder, detectors to splunk-observability-native-ops, and AI infrastructure products to dedicated skills where available. UI-only AI Agent Monitoring connection/index selection remains deeplink/handoff. |
| `splunk-observability-database-monitoring-setup` | N/A | No Splunk Cloud app install; DBMon uses the customer-managed Splunk OTel Collector runtime rendered by splunk-observability-otel-collector-setup | Rendered Kubernetes clusterReceiver overlay, Linux collector fragment, placeholder-only DB credential Secret stubs, and gateway-routing reference for Splunk Database Monitoring events | Render/validate-first Splunk Database Monitoring workflow for PostgreSQL, Microsoft SQL Server, and Oracle Database. Enforces DBMon realm availability, collector version floors, official support matrix, clusterReceiver placement, logs/dbmon event exporter, and file/env/Secret-only credential handling. |
| `splunk-observability-aws-integration` | N/A | No Splunk Cloud app install; AWSCloudWatch integration is configured through Splunk Observability Cloud APIs, CloudFormation, Terraform, and AWS-side IAM/Metric Streams resources | Rendered REST payloads, IAM policy JSON, CloudFormation and StackSets stubs, Terraform configuration, drift reports, PrivateLink notes, and handoff runbooks for adjacent AWS telemetry paths | Standalone reusable Splunk Observability Cloud AWS integration workflow for polling, Splunk-managed Metric Streams, AWS-managed Metric Streams, and Terraform. Enforces canonical AWSCloudWatch field conflicts, file-based token handling, region and realm guardrails, recommended-stats selection, multi-account StackSets emission, and Splunk_TA_AWS handoff for AWS logs. |
| `splunk-observability-k8s-auto-instrumentation-setup` | N/A | No Splunk Cloud app install; overlay on splunk-observability-otel-collector-setup that renders Instrumentation CRs, annotation patches, and the optional OBI DaemonSet for customer-managed Kubernetes clusters | Rendered Instrumentation CR manifests (per-language images + env), namespace + workload strategic-merge-patches targeting spec.template.metadata.annotations, annotation backup ConfigMap for clean revert, OpenShift SCC stub when OBI is enabled, and idempotent apply + uninstall helper scripts | Zero-code application auto-instrumentation for Java / Node.js / Python / .NET / Go / Apache / Nginx / SDK workloads. Overlay on splunk-observability-otel-collector-setup (which installs the operator + CRDs). Includes AlwaysOn Profiling + runtime metrics wiring, propagator + sampler configuration, multi-CR support behind the operator multi-instrumentation gate, vendor-coexistence detection, --discover-workloads helper, selective --target apply/uninstall, and --gitops-mode YAML-only rendering. |
| `splunk-observability-k8s-frontend-rum-setup` | N/A | No Splunk Cloud app install; standalone reusable skill (RUM beacons direct to rum-ingest.<realm>.observability.splunkcloud.com) that renders Splunk Browser RUM (@splunk/otel-web 2.x) + Session Replay (Splunk recorder) injection assets for customer-managed Kubernetes clusters | Rendered K8s manifests for one of four injection modes (nginx pod-side ConfigMap with sub_filter, ingress-nginx configuration-snippet annotation, busybox+emptyDir initContainer rewriter for distroless, runtime-config ConfigMap for npm-bundled SDK), injection-backup ConfigMap, full SplunkRum.init + Frustration Signals 2.0 + Session Replay surfaces, JavaScript source-map upload helper wrapping the splunk-rum CLI + @splunk/rum-build-plugins Webpack plugin, RUM-to-APM Server-Timing trace-linking validation | Splunk Browser RUM + Session Replay injection. NOT AppDynamics BRUM (handled by cisco-appdynamics-setup). Two distinct credential files: SPLUNK_O11Y_RUM_TOKEN_FILE for the browser-embedded RUM token, SPLUNK_O11Y_TOKEN_FILE reused for the server-to-server source-map upload. Hands off RUM dashboards to splunk-observability-dashboard-builder, RUM detectors to splunk-observability-native-ops, the SIM rum modular input to splunk-observability-cloud-integration-setup, and RUM-to-APM trace linking to splunk-observability-k8s-auto-instrumentation-setup. |
| `splunk-observability-dashboard-builder` | N/A | No Splunk Cloud app install; renders Splunk Observability Cloud dashboard groups, charts, dashboards, and apply plans | Validate and optionally apply classic Observability dashboard API payloads; access tokens stay file-based and are never placed in chat or command arguments | Dashboard composition workflow for Observability dashboard groups, charts, variables, detector links, runbooks, rendered API payloads, and optional applies. |
| `splunk-observability-native-ops` | N/A | No Splunk Cloud app install; renders native Splunk Observability Cloud operations and handoff plans | Validate and optionally apply Observability API payloads for detectors, teams, alert routing, Synthetics, and APM trace/topology checks; render deeplinks and handoffs for SLOs, RUM, service maps, modern logs charts, and On-Call deeplink handoffs (full On-Call coverage lives in splunk-oncall-setup) | Native Observability operations workflow; complements OTel collection and classic dashboard rendering without Splunk Platform runtime placement. |
| `splunk-oncall-setup` | N/A | Splunk-side companion apps install through ACS or REST: Splunkbase 3546 (victorops_app, alert action) on a search head or SHC deployer; Splunkbase 4886 (TA-splunk-add-on-for-victorops, public-API ingest) on a heavy forwarder; Splunkbase 5863 (splunkoncall, SOAR connector) installs through Splunk SOAR rather than splunk-app-install | Render and apply the full Splunk On-Call lifecycle through the public API at api.victorops.com (X-VO-Api-Id + X-VO-Api-Key file-based auth) with per-endpoint rate-limit governors; send REST endpoint and generic email alerts; pre-create the four indexes the Add-on macros expect (victorops_users / victorops_teams / victorops_oncall / victorops_incidents); seed the alert-action mycollection KV-store; toggle the recovery_polling saved search; render ITSI NEAP, ES Adaptive Response, and Observability detector-recipient handoff stubs | Render-first lifecycle for Splunk On-Call (formerly VictorOps). Splunkbase apps: 3546 (victorops_app), 4886 (TA-splunk-add-on-for-victorops), 5863 (splunkoncall SOAR connector). Supersedes the partial on_call block in splunk-observability-native-ops which now defers via deeplink-only handoff. |
| `splunk-license-manager-setup` | N/A | Not a Splunk Cloud install path; Splunk Cloud licensing is Splunk-managed | Renders self-managed Enterprise license install commands, REST license group / pool payloads, and per-peer `splunk edit licenser-localpeer` wrappers | Self-managed Splunk Enterprise license manager / peer / pool / group lifecycle. Co-locates with cluster-manager, MC, deployment server, SHC deployer, search head, or indexer. |
| `splunk-edge-processor-setup` | N/A | No Splunk Cloud app install; Edge Processor runtime is rendered for customer-managed Linux hosts and joined to a Splunk Cloud Platform tenant or Splunk Enterprise 10.0+ data management node | Renders EP control-plane object (TLS / mTLS), source types, destinations (Splunk S2S, Splunk HEC, Amazon S3, syslog), SPL2 pipelines, apply-objects orchestrator, per-host install (systemd / no-systemd / Docker), and forwarder outputs.conf | Default-destination guard prevents silent data loss. Emits ACS allowlist hand-off stub for s2s + hec features when destinations target Splunk Cloud. |
| `splunk-indexer-cluster-setup` | N/A | Not a Splunk Cloud install path; Splunk Cloud indexer clusters are Splunk-managed | Renders self-managed Enterprise single-site or multisite cluster manager, peer, and SH server.conf snippets; sequenced bootstrap; cluster bundle validate / status / apply / rollback; rolling restart (default / searchable / forced); peer offline (fast / enforce-counts); maintenance mode; manager redundancy (HAProxy + DNS); migration to multisite; non-clustered-to-clustered migration | Sits above splunk-enterprise-host-setup (per-host install). Emits a license-peers hand-off stub for splunk-license-manager-setup. |
| `splunk-cloud-acs-allowlist-setup` | N/A | No Splunk Cloud app install; manages Splunk Cloud ACS IP allowlists for all 7 ACS features | Renders desired-state plan for acs / search-api / hec / s2s / search-ui / idm-api / idm-ui (IPv4 + IPv6); preflight enforces AWS 200/feature + 230/group and GCP 200/feature limits; lock-out protection refuses acs feature edits without operator IP; status polling on /adminconfig/v2/status; optional terraform-snippets.tf via splunk/scp | Explicit user-driven counterpart to acs_helpers.sh acs_ensure_search_api_access. FedRAMP High excluded (Splunk Support only). |
| `splunk-enterprise-host-setup` | N/A | Not a Splunk Cloud install path; bootstraps customer-managed Enterprise hosts only | Local or SSH-driven Linux host bootstrap for search-tier, indexer, and heavy-forwarder roles | Enterprise runtime bootstrap workflow for standalone or single-site clustered hosts. |
| `splunk-enterprise-kubernetes-setup` | N/A | Not a Splunk Cloud install path; renders customer-managed Splunk Enterprise Kubernetes deployments | Rendered SOK Helm assets or Splunk POD cluster-config.yaml and installer helpers | Self-managed Kubernetes runtime workflow for SOK S1/C3/M4 or Splunk POD on Cisco UCS. |
| `cisco-spaces-setup` | 8485 | ACS Splunkbase | REST via UCC custom stream/input handlers | Cisco EULA license-ack required. Firehose streaming input for Cisco Spaces indoor location analytics. |
| `splunk-observability-cloud-integration-setup` | N/A | No Splunk Cloud app install of its own; orchestrates pairing + Discover-app + LOC + SIM Add-on (Splunkbase 5247) + cross-skill handoffs to splunk-cloud-acs-allowlist-setup, splunk-app-install, and splunk-itsi-config | Render-first integration setup: token-auth flip, Unified Identity or Service Account pairing (acs observability + /adminconfig/v2/observability/sso-pairing), multi-org default-org deeplink, Centralized RBAC (enable-capabilities + enable-centralized-rbac), Discover Splunk Observability Cloud app five Configurations tabs, Log Observer Connect service-account user/role/workload rule, Related Content + Real Time Metrics capability assignments, Dashboard Studio O11y metrics, Splunk Infrastructure Monitoring Add-on account + curated SignalFlow modular inputs with MTS sizing preflight; file-based tokens only, --i-accept-rbac-cutover guard for the destructive RBAC step | Single skill that turns a Splunk Cloud Platform or Splunk Enterprise stack into a fully-paired Splunk Observability Cloud experience. Uses Splunk_TA_sim (Splunkbase 5247) for the in-Splunk navigation surface (sim SPL command + streaming modular inputs). |
| `splunk-observability-cloud-integration-setup` (SIM Add-on) | 5247 | ACS Splunkbase (id 5247); install on search heads + Inputs Data Manager | REST via UCC custom account + modular-input handlers under /servicesNS/nobody/Splunk_TA_sim | Splunk Infrastructure Monitoring Add-on. Provides the sim SPL command and the splunk_infrastructure_monitoring_data_streams modular input. Hard cap: 250,000 MTS per modular input. Splunk Synthetic Monitoring Add-on (Splunkbase 5608) is archived (deprecated) and replaced by SIM streams. |

## Stream Heavy Forwarder Model

For Splunk Stream on Splunk Cloud:

- install `splunk_app_stream` on the Splunk Cloud search tier
- install `Splunk_TA_stream` on a customer-controlled HF/UF
- use the local overlay template in:
  `skills/splunk-stream-setup/templates/splunk-cloud-hf-netflow-any/`
- configure HF forwarding to Splunk Cloud at the host layer

## SC4S External Collector Model

For Splunk Connect for Syslog on Splunk Cloud:

- create or validate indexes and HEC tokens against the Cloud stack
- run the SC4S syslog-ng container on infrastructure you control
- send SC4S output directly to Splunk Cloud HEC on `443`
- keep SC4S runtime files, token material, and local archive/disk-buffer storage
  on the customer-managed host or Kubernetes cluster

## SC4SNMP External Collector Model

For Splunk Connect for SNMP on Splunk Cloud:

- create or validate indexes and HEC tokens against the Cloud stack
- run the SC4SNMP poller and trap listener on infrastructure you control
- send SC4SNMP output directly to Splunk Cloud HEC on `443`
- keep SC4SNMP runtime files, token material, inventory, and local secret files
  on the customer-managed host or Kubernetes cluster

## External OpenTelemetry Collector Model

For the Splunk Distribution of OpenTelemetry Collector on Splunk Cloud
or Splunk Observability Cloud:

- render Kubernetes Helm values or Linux installer wrappers locally
- keep Observability access tokens and optional Splunk Platform HEC tokens
  in local secret files
- deploy the collector on customer-managed Kubernetes clusters or Linux hosts
- send metrics, traces, profiling, discovery, and Kubernetes events to
  Splunk Observability Cloud
- send Kubernetes container logs to Splunk Platform HEC only when a HEC URL
  and token file are explicitly provided

## Cloud Access Architecture

Splunk Cloud exposes two distinct API surfaces. The scripts in this repo use
both depending on the operation.

### ACS vs Search-Tier REST (8089)

| Operation | ACS (no 8089 needed) | REST 8089 required |
| --- | --- | --- |
| App install / uninstall | Yes | -- |
| Index create / check | Yes | -- |
| HEC token management | Yes | -- |
| Stack restart | Yes | -- |
| IP allowlist management | Yes | -- |
| TA account setup (OAuth, API keys) | -- | Yes |
| Input enablement / configuration | -- | Yes |
| Conf / macro updates | -- | Yes |
| Saved search toggles | -- | Yes |
| Validation (app state, data flow) | -- | Yes |
| Oneshot search | -- | Yes |

Port 443 on Splunk Cloud serves Splunk Web (the browser UI). The full REST API
(`/servicesNS/...`, `/services/...`) is documented exclusively on port 8089.
ACS does not expose app-specific custom REST handlers.

### Automatic Search-API Access

When a script detects a Cloud target, the shared helpers automatically:

1. **Resolve the current search head** via `acs config current-stack` and
   build a direct search-head REST URL (`https://sh-i-*.stack.splunkcloud.com:8089`).
2. **Switch to stack-local credentials** (`STACK_USERNAME` / `STACK_PASSWORD`)
   for 8089 authentication.
3. **Add the current public IP to the search-api allowlist** via
   `acs ip-allowlist create search-api --subnets <ip>/32` if it is not already
   listed.

This means a user with valid ACS credentials can run any skill against Splunk
Cloud without manually configuring the search-api IP allowlist or knowing the
direct search-head hostname.

To disable the automatic allowlist management (for example, in environments
where IP allowlists are controlled externally), set:

```bash
export SPLUNK_SKIP_ALLOWLIST="true"
```

### Why Direct Search Heads?

After an ACS app install, the load-balanced stack hostname
(`stack.splunkcloud.com:8089`) can take time to reflect the new app across all
search-head cluster members. The direct search-head URL bypasses this
propagation delay and sees the installed app immediately.

## What `_unpacked` Means

The `_unpacked` trees exist only so we can:

- inspect package internals
- identify Cloud compatibility risks
- document vendor package limitations

They are not the normal installation source for this repo's Cloud workflow.
