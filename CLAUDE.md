# Splunk Platform and Cisco Skills — Claude Code Context

This repository is a working library of Cursor, Codex, and Claude Code agent
skills, MCP tooling, intake templates, reference docs, and shell automation for
planning, rendering, installing, configuring, validating, and handing off Splunk
Platform, Splunk Cloud, Splunk Observability Cloud, Cisco, and adjacent
operational integrations.

It goes well beyond Technology Add-on setup. The catalog covers Cisco product
onboarding, Splunk apps and TAs, Enterprise Security and the broader Splunk
security portfolio, ITSI, SOAR, On-Call, Observability Cloud integrations,
dashboards, detectors, OpenTelemetry collectors, Kubernetes APM
auto-instrumentation, Browser RUM and Session Replay, AWS and ThousandEyes
integrations, HEC, ACS allowlists, PKI, SmartStore, federated search, workload
management, Monitoring Console, license management, indexer clusters, Edge
Processor, Stream, SC4S, SC4SNMP, Universal Forwarders, Linux Splunk Enterprise
hosts, self-managed Kubernetes runtimes, and external-collector topologies.
Most workflows are render-first and validation-heavy, with explicit apply
phases and secret-file guardrails for production changes.

## How To Use This Repo With Claude Code

When the user asks about a Cisco product or Splunk app/workflow, find the matching
skill in the table below and read `skills/<skill-name>/SKILL.md` for complete
instructions. If more detail is needed, also read `skills/<skill-name>/reference.md`.

The user can also invoke skills directly as slash commands (e.g. `/cisco-catalyst-ta-setup`).

## Skill Catalog

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
| `cisco-enterprise-networking-setup` | `cisco-catalyst-app` | Configure the visualization app's macros and related app settings |
| `cisco-thousandeyes-setup` | `ta_cisco_thousandeyes` | Configure ThousandEyes OAuth, HEC, streaming/polling inputs, and dashboards |
| `cisco-thousandeyes-mcp-setup` | Official ThousandEyes MCP Server (`https://api.thousandeyes.com/mcp`) | Render and apply Model Context Protocol client configurations for Cursor / Claude Code / Codex / VS Code / AWS Kiro; gates the write/Instant-Test tool group behind `--accept-te-mcp-write-tools` |
| `cisco-isovalent-platform-setup` | Cilium / Tetragon / Hubble Enterprise on Kubernetes (NOT a Splunk TA installer) | Install the Isovalent platform itself: OSS (`cilium/cilium` + `cilium/tetragon` from `helm.cilium.io`) or Enterprise (`isovalent/*` from `helm.isovalent.com`, license + private chart access). Tetragon export defaults to `mode: file` for `splunk-observability-isovalent-integration`. |
| `splunk-itsi-setup` | `SA-ITOA` | Install and validate Splunk ITSI; integration readiness for ThousandEyes |
| `splunk-itsi-config` | Native ITSI objects, service trees, and supported ITSI content packs | Preview, apply, and validate ITSI entities, services, KPIs, dependencies, template links, service trees, NEAPs, and selected content packs from YAML specs |
| `splunk-enterprise-security-install` | `SplunkEnterpriseSecuritySuite` | Install, post-install, and validate Splunk Enterprise Security on standalone search heads or SHC deployers |
| `splunk-enterprise-security-config` | Splunk Enterprise Security configuration | Configure ES indexes, roles, data models, enrichment, detections, and operational validation |
| `splunk-security-portfolio-setup` | Splunk security product router | Resolve ES, SOAR, Security Essentials, UBA, Attack Analyzer, ARI, and related security offerings to setup, install-only, bundled ES, or handoff workflows |
| `splunk-security-essentials-setup` | `Splunk_Security_Essentials` | Install and validate Splunk Security Essentials, content recommendations, and starter posture dashboards |
| `splunk-asset-risk-intelligence-setup` | `SplunkAssetRiskIntelligence` | Install and validate ARI indexes, KV Store readiness, ARI roles, and ES Exposure Analytics handoff |
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
| `splunk-federated-search-setup` | Splunk Federated Search | Render and validate self-managed Splunk-to-Splunk standard or transparent providers, standard-mode federated indexes, and SHC replication assets |
| `splunk-index-lifecycle-smartstore-setup` | Splunk Index Lifecycle / SmartStore | Render and validate SmartStore `indexes.conf`, `server.conf`, and `limits.conf` assets for indexers or cluster managers |
| `splunk-monitoring-console-setup` | Splunk Monitoring Console | Render and validate self-managed distributed or standalone Monitoring Console assets, including auto-config, peer/group review, forwarder monitoring, and platform alerts |
| `splunk-enterprise-host-setup` | Splunk Enterprise runtime | Bootstrap Linux Splunk Enterprise hosts as search-tier, indexer, heavy-forwarder, cluster-manager, indexer-peer, SHC deployer, or SHC member |
| `splunk-enterprise-kubernetes-setup` | Splunk Enterprise on Kubernetes | Render, preflight, apply, and validate SOK S1/C3/M4 or Splunk POD on Cisco UCS |
| `splunk-observability-otel-collector-setup` | Splunk Observability Cloud OTel Collector | Render, apply, and validate Splunk Distribution of OpenTelemetry Collector assets for Kubernetes clusters and Linux hosts, including Splunk Platform HEC token handoff helpers |
| `splunk-observability-ai-agent-monitoring-setup` | Splunk AI Agent Monitoring + AI Infrastructure Monitoring | Render, validate, diagnose, and safely apply AI Agent Monitoring setup plans, including GenAI Python instrumentation packages, instrumentation-side evaluations, histogram collector readiness, HEC/Log Observer Connect handoffs, dashboards, detectors, and full AI Infrastructure Monitoring product coverage |
| `splunk-observability-database-monitoring-setup` | Splunk Observability Cloud Database Monitoring | Render and validate DBMon collector overlays for PostgreSQL, Microsoft SQL Server, and Oracle Database through the Splunk OTel Collector; enforces realm, version, support-matrix, clusterReceiver, and secret-handling guardrails |
| `splunk-observability-k8s-auto-instrumentation-setup` | Zero-code K8s app auto-instrumentation | Overlay on `splunk-observability-otel-collector-setup`: render, apply, verify, and uninstall per-language OpenTelemetry Operator Instrumentation CRs (Java / Node.js / Python / .NET / Go / Apache / Nginx / SDK), workload annotation strategic-merge patches targeting `spec.template.metadata.annotations` with backup/restore ConfigMap for clean revert, multi-CR support behind the operator multi-instrumentation gate, Splunk OBI (eBPF) DaemonSet with OpenShift SCC stub, AlwaysOn Profiling + runtime metrics (`SPLUNK_PROFILER_*` / `SPLUNK_METRICS_*`), propagator + sampler configuration, Fargate gateway-endpoint path, vendor-coexistence detection (Datadog / New Relic / AppDynamics / Dynatrace), `--discover-workloads` helper, selective `--target` apply/uninstall, and `--gitops-mode` YAML-only rendering |
| `splunk-observability-k8s-frontend-rum-setup` | Splunk Browser RUM + Session Replay injection into K8s frontends | Standalone reusable (RUM beacons direct to `rum-ingest.<realm>.observability.splunkcloud.com`, no OTel collector required): render, apply, verify, and uninstall Splunk Browser RUM (`@splunk/otel-web` 2.x) + Session Replay (Splunk recorder) injection across four modes — nginx pod-side ConfigMap with `sub_filter` on `</head>`, ingress-nginx `configuration-snippet` annotation, `busybox`+`emptyDir` initContainer HTML rewriter (distroless-safe), and runtime-config ConfigMap with `window.SPLUNK_RUM_CONFIG` for npm-bundled SDK; injection-backup ConfigMap for clean revert; full `SplunkRum.init` surface (cookieDomain / persistance / user.trackingMode / disableBots / disableAutomationFrameworks / globalAttributes / ignoreUrls / exporter.otlp / tracer.sampler / spaMetrics / privacy.{maskAllText,sensitivityRules} / per-instrumentation toggles); Frustration Signals 2.0 (rage / dead / error / thrashed cursor with all knobs); Session Replay (`sensitivityRules` + `features.{canvas,video,iframes,packAssets,cacheAssets,backgroundServiceSrc}` + sampler) gated behind `--accept-session-replay-enterprise`; JavaScript source-map upload helper wrapping the `splunk-rum` CLI + `@splunk/rum-build-plugins` Webpack plugin + GitHub Actions / GitLab CI snippets, reusing `SPLUNK_O11Y_TOKEN_FILE`; RUM-to-APM `Server-Timing: traceparent` linking validation that emits `handoff-auto-instrumentation.sh` on miss; multi-workload spec with per-workload `injection_mode` override; distroless image auto-detection; ingress-nginx CVE-2021-25742 `allow-snippet-annotations` preflight; version-pin enforcement (`v1` default, `latest` rejected without `--allow-latest-version`); SRI hash emission for exact-version CDN pins; IE11 legacy build opt-in; both `cdn.observability.splunkcloud` (default) and legacy `cdn.signalfx` endpoint domains; `--guided` interactive Q&A walk-through; hands off RUM dashboards to `splunk-observability-dashboard-builder`, RUM detectors to `splunk-observability-native-ops`, the SIM `rum` modular input to `splunk-observability-cloud-integration-setup`. Explicitly NOT AppDynamics BRUM (handled by `cisco-appdynamics-setup`) |
| `splunk-observability-cloud-integration-setup` | Splunk Platform <-> Splunk Observability Cloud | Pair Splunk Cloud Platform / Splunk Enterprise with Splunk Observability Cloud end-to-end: token-auth flip, Unified Identity or Service Account pairing, multi-org default-org, Centralized RBAC, Discover Splunk Observability Cloud app's five Configurations tabs, Log Observer Connect (SCP + SE TLS), Related Content + Real Time Metrics, Dashboard Studio O11y metrics, and the Splunk Infrastructure Monitoring Add-on (Splunk_TA_sim, 5247) install + account + curated SignalFlow modular inputs |
| `splunk-observability-thousandeyes-integration` | ThousandEyes -> Splunk Observability Cloud | Render and apply the full TE -> O11y wiring: Integration 1.0 OpenTelemetry stream (`POST /v7/streams` to ingest.<realm>.signalfx.com/v2/datapoint/otlp), Integrations 2.0 Splunk Observability APM connector, full TE asset lifecycle (tests, alert rules, labels, tags, TE-side dashboards, Templates with Handlebars-only credential placeholders); per-test-type SignalFlow dashboards + detectors handed off to `splunk-observability-dashboard-builder` and `splunk-observability-native-ops` |
| `splunk-observability-isovalent-integration` | Isovalent (Cilium / Hubble / Tetragon) -> Splunk Observability Cloud + Splunk Platform | Render the Splunk OTel collector overlay (seven `prometheus/isovalent_*` scrape jobs + `filter/includemetrics` + cilium-dnsproxy fix); Splunk Platform logs DEFAULT via OTel filelog receiver + hostPath mount + `extraFileLogs.filelog/tetragon` (production-validated); legacy fluentd splunk_hec behind `--legacy-fluentd-hec` (DEPRECATED); hands off Tetragon log ingestion to `cisco-security-cloud-setup` (`PRODUCT=isovalent`, sourcetype `cisco:isovalent`, index `cisco_isovalent`) |
| `splunk-observability-cisco-nexus-integration` | Cisco Nexus 9000 fabric -> Splunk Observability Cloud | Standalone reusable: clusterReceiver `cisco_os` overlay (PR #45562 multi-device + global-scrapers format, contrib v0.149.0+) with K8s Secret manifest stub for SSH credentials, dashboards (port utilization, errors, drops, CPU/memory) and detectors (interface down, packet drop rate, CPU/memory pressure). Companion to `cisco-dc-networking-setup` (Splunk Platform TA path). |
| `splunk-observability-cisco-intersight-integration` | Cisco Intersight (UCS) -> Splunk Observability Cloud | Standalone reusable: separate `intersight-otel` namespace + Secret manifest stub + Deployment + ConfigMap pointing at the Splunk OTel agent's OTLP gRPC endpoint; dashboards (UCS power/thermal/fan/network/alarms/advisories/VM count) and detectors (alarm spike, security advisory delta, host temp/power, fan failure). Companion to `cisco-intersight-setup` (Splunk Platform TA path). |
| `splunk-observability-nvidia-gpu-integration` | NVIDIA GPUs (DCGM Exporter) -> Splunk Observability Cloud | Standalone reusable: `receiver_creator/dcgm-cisco` (parameterized; explicitly NOT `receiver_creator/nvidia` to avoid collision with chart autodetect); dual-label DCGM discovery (`app` + `app.kubernetes.io/name`); default unfiltered `metrics/nvidia-metrics` pipeline; `--enable-dcgm-pod-labels` patch (env-var + RBAC + SA-token + kubelet mount) for the well-known GPU Operator pod-label gap. Works for any GPU cluster (NVIDIA DGX, AI Pod, generic K8s + GPUs). |
| `splunk-observability-cisco-ai-pod-integration` | Cisco AI Pod (UCS + Nexus + NVIDIA GPUs + NIM/vLLM + storage) -> Splunk Observability Cloud | Umbrella that composes Nexus + Intersight + NVIDIA GPU components via subprocess + Python deep-merge AND adds NIM scrape (TWO modes: `receiver_creator` simple vs `endpoints` precise + `rbac.customRules` patch), vLLM, Milvus, NetApp Trident (port 8001), Pure Portworx (17001+17018), Redfish exporter (user-supplied), `k8s_attributes/nim` for `model_name` extraction, dual-pipeline filtering pattern, OpenShift defaults (kubeletstats `insecure_skip_verify`, certmanager off, cloudProvider empty), `--workshop-mode` multi-tenant.sh, OpenShift SCC helper. Mirrors `signalfx/splunk-opentelemetry-examples/collector/cisco-ai-ready-pods` + production-validated atl-ocp2 OpenShift cluster. |
| `splunk-observability-aws-integration` | AWS -> Splunk Observability Cloud | Standalone reusable: render, apply, validate, discover, and diagnose the `AWSCloudWatch` integration end-to-end across all four documented connection paths (polling, Splunk-managed Metric Streams, AWS-managed Metric Streams, Terraform). Emits per-use-case IAM JSON (foundation, polling, streams, tag sync, Cassandra-Keyspaces special-case ARN list), regional or StackSets CloudFormation stubs from `signalfx/aws-cloudformation-templates`, Splunk-side Terraform pinned to `signalfx` provider `~> 9.0`, and a canonical REST payload (POST/PUT `/v2/integration` with `X-SF-Token` admin user API access token). Enforces the canonical conflict matrix: `services` vs `namespaceSyncRules`, `customCloudWatchNamespaces` (capital W per live API) vs `customNamespaceSyncRules`, `metricStreamsManagedExternally` requires `useMetricStreamsSync`. Surfaces AWS-recommended-stats catalog (`collectOnlyRecommendedStats`), per-namespace per-metric stat allow-list (`metricStatsToSyncs`), adaptive polling (`inactiveMetricsPollRate`), AWS PrivateLink ingest stubs (default legacy `signalfx.com` domain per Sep-2024 doc), multi-account / AWS Organizations CFN StackSets emission with `use_org_service_managed`, drift detection with `--quickstart-from-live`, and the documented troubleshooting catalog. Live-validated against the operator's existing us1 integration (Splunk-side AWS account `562691491210`). FedRAMP / GovCloud / China carve-outs encoded. Hand-offs to `splunk-app-install` for `Splunk_TA_AWS` (Splunkbase 1876, min v8.1.1; uninstall `Splunk_TA_amazon_security_lake` first if present), to `splunk-observability-cloud-integration-setup` for Log Observer Connect, to `splunk-observability-dashboard-builder` for AWS dashboards, to `splunk-observability-native-ops` for AutoDetect detectors, to `splunk-observability-otel-collector-setup` for richer EC2/EKS host telemetry, and to a future `splunk-observability-aws-lambda-apm-setup` companion (Lambda layer publisher AWS account `254067382080`). Explicitly NOT AWS log ingestion (handed off to `Splunk_TA_AWS`; `enableLogsSync` is deprecated and rejected). |
| `splunk-observability-dashboard-builder` | Splunk Observability Cloud dashboards | Render, validate, and optionally apply classic Observability dashboard groups, charts, and dashboards from natural-language, JSON, or YAML specs |
| `splunk-observability-native-ops` | Splunk Observability Cloud native operations | Render, validate, and optionally apply supported native Observability operations for detectors, alert routing, Synthetics, APM, RUM, logs, and On-Call deeplink handoffs (full Splunk On-Call coverage lives in `splunk-oncall-setup`) |
| `splunk-oncall-setup` | Splunk On-Call (formerly VictorOps) | Render, validate, and apply the full Splunk On-Call lifecycle: teams, users + contact methods, rotations, escalation policies, routing keys, scheduled overrides, personal paging policies, alert rules / Rules Engine, maintenance mode, incidents, notes, chat, stakeholder messages, REST endpoint and generic email alert payloads, plus Splunk-side companion apps (Splunkbase 3546 alert action `victorops_app`, 4886 Splunk Add-on for On-Call `TA-splunk-add-on-for-victorops` on a heavy forwarder with the four `victorops_*` indexes pre-created, 5863 SOAR connector `splunkoncall`, ITSI NEAP, ES Adaptive Response, Observability detector recipient deeplink) |
| `splunk-stream-setup` | Splunk Stream stack | Install and configure Splunk Stream components |
| `splunk-connect-for-syslog-setup` | SC4S external collector | Prepare Splunk HEC/indexes and render or apply Docker, Podman, systemd, or Helm assets for Splunk Connect for Syslog |
| `splunk-connect-for-snmp-setup` | SC4SNMP external collector | Prepare Splunk HEC/indexes and render or apply Docker Compose or Helm assets for Splunk Connect for SNMP |
| `splunk-license-manager-setup` | Splunk Enterprise license manager / peers / pools / groups / messages | Install licenses, switch groups, configure peers, allocate pools, audit usage and violations, validate version compatibility |
| `splunk-soar-setup` | `splunk_soar-unpriv` (single + cluster) + `splunk_app_soar` (6361) + Splunk App for SOAR Export (3411) + Splunk SOAR Automation Broker | Install SOAR On-prem (single + cluster with external PG/GlusterFS/Elasticsearch), help with SOAR Cloud onboarding, install Automation Broker on Docker/Podman, install Splunk-side SOAR apps, ready ES integration, backup/restore |
| `splunk-edge-processor-setup` | Splunk Edge Processor instances + cloud / Enterprise control plane | Add EP control-plane object, install instances on Linux (systemd or not), scale to multi-instance, manage source types / destinations / SPL2 pipelines, apply pipelines, validate health |
| `splunk-indexer-cluster-setup` | Splunk Enterprise indexer cluster (single-site, multisite, redundant managers) | Bootstrap manager(s) / peers / SHs, manage cluster bundle (validate / apply / rollback), rolling restart (default / searchable / forced), peer offline (fast / enforce-counts), maintenance mode, single-site to multisite migration, manager replacement |
| `splunk-cloud-acs-allowlist-setup` | Splunk Cloud ACS IP allowlists (all 7 features, IPv4 + IPv6) | Render plan, preflight (subnet limits, lock-out protection, FedRAMP carve-out), apply, audit / diff, optional Terraform emission |
| `splunk-enterprise-public-exposure-hardening` | On-prem Splunk Enterprise public-internet exposure | Render Splunk-side hardening (web/server/inputs/outputs/authentication/authorize/limits/commands.conf + metadata) plus reverse-proxy (nginx/HAProxy) + firewall + WAF/CDN handoff; preflight 20-step + validate live probes; SVD floor enforcement; refuses to apply without `--accept-public-exposure` |
| `splunk-platform-pki-setup` | Splunk Enterprise platform PKI lifecycle | Render Private PKI (operator becomes the CA) or Public PKI (CSR + handoff to commercial CA / Vault PKI / ACME / AD CS / EJBCA), distribute per-component certs across Splunk Web / splunkd / S2S / HEC / KV Store / indexer cluster (incl. `[replication_port-ssl://9887]`) / SHC / License Manager / Deployment Server / Monitoring Console / Federated Search / DMZ HF / UF fleet / Edge Processor / SAML SP signing / LDAPS / `splunk` CLI `cacert.pem`; enforce KV Store dual-EKU + hostname validation + opt-in mTLS; FIPS 140-2 / 140-3 wiring via `splunk-launch.conf`; three TLS algorithm presets (`splunk-modern`, `fips-140-3`, `stig`); refuse default Splunk certs; emit a delegated rotation runbook that hands off to `splunk-indexer-cluster-setup --phase rolling-restart` |

## Splunk MCP Server

If `.mcp.json` exists at the project root, the Splunk MCP server is available as the
`splunk-mcp` tool through the tracked `splunk-mcp-rendered/run-splunk-mcp.js`
bridge. The local token file (`splunk-mcp-rendered/.env.splunk-mcp`) only exists
after running the `splunk-mcp-server-setup` skill. Use MCP search tools for live
Splunk queries when available.

## Local Skill MCP Server

The project also exposes a local `splunk-cisco-skills` MCP server through
`agent/run-splunk-cisco-skills-mcp.py`. Install its Python dependencies with:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-agent.txt
```

If an internal pip index does not mirror the MCP SDK, install from public PyPI
explicitly:

```bash
pip install --index-url https://pypi.org/simple -r requirements-agent.txt
```

The launcher automatically prefers `.venv/bin/python` when the repo-local venv
exists, so Claude Code and Cursor do not need to inherit an activated shell.
Claude Code reads `.mcp.json`; Cursor reads `.cursor/mcp.json`; Codex needs a
one-time registration with `bash agent/register-codex-splunk-cisco-skills-mcp.sh`.

This server provides read-only skill catalog, template, product-resolution, and
planning tools by default. Read-only plans can run with explicit confirmation.
Mutating setup, install, or configure scripts are disabled unless the MCP server
process is started with `SPLUNK_SKILLS_MCP_ALLOW_MUTATION=1`; all execution tools
require a matching plan hash and explicit confirmation.

Plans are single-use and stored in memory for the MCP server session: a plan
is consumed when it executes, and the entire plan store is lost if the server
restarts. If a plan hash is rejected as unknown, re-run the plan step to get a
fresh hash. `SPLUNK_SKILLS_MCP_ALLOW_MUTATION=1` is a server-wide toggle — it
enables mutating execution for all clients connected to that server process.

## Credentials

All scripts load deployment settings from a project-root `credentials` file first,
fall back to `~/.splunk/credentials`, and honor `SPLUNK_CREDENTIALS_FILE` for alternate
files. Run `bash skills/shared/scripts/setup_credentials.sh` to create the file
interactively, or copy and edit `credentials.example`.

Splunk Observability Cloud skills read `SPLUNK_O11Y_REALM` and
`SPLUNK_O11Y_TOKEN_FILE` from the same credentials file. Store only the realm
and token-file path there; keep the Observability API token value in a separate
chmod 600 file.

## Secure Credential Handling Rules

### Agent Rules

1. **NEVER ask** the user for passwords, API keys, tokens, client secrets, or any
   other secret in conversation. This includes Splunk credentials, device passwords,
   Meraki API keys, Intersight client secrets, Splunkbase passwords, and any other
   sensitive value.

2. **NEVER pass** `SPLUNK_USER`, `SPLUNK_PASS`, `SB_USER`, `SB_PASS`, or any secret
   as an environment variable prefix in shell commands. For example, do NOT run:
   `SPLUNK_PASS="secret" bash script.sh`

3. **NEVER pass** secrets as command-line arguments (e.g., `--password mysecret`).
   Use file-based alternatives instead (`--password-file /path/to/file`).

4. **Splunk credentials** are stored in the project-root `credentials` file
   (chmod 600, gitignored) and read automatically by all skill scripts via the
   shared credential helper library at `skills/shared/lib/credential_helpers.sh`.
   The library also falls back to `~/.splunk/credentials` if the project file
   does not exist.

5. If Splunk credentials are not yet configured, guide the user to run:
   ```bash
   bash skills/shared/scripts/setup_credentials.sh
   ```
   Or copy and edit the example:
   ```bash
   cp credentials.example credentials && chmod 600 credentials
   ```

6. **Device credentials** (device passwords, API keys, client secrets) should be
   handled by instructing the user to create a temporary file without putting
   the secret in shell history:
   ```bash
   bash skills/shared/scripts/write_secret_file.sh /tmp/secret_file
   ```
   Then pass the file path to the script (e.g., `--password-file /tmp/secret_file`).
   Instruct the user to delete the file after use.

   Splunk Observability Cloud API tokens follow the same pattern: set
   `SPLUNK_O11Y_TOKEN_FILE` to the local file path, never to the token value.

7. You MAY freely ask for non-secret values: account names, hostnames, IP addresses,
   regions, index names, organization IDs, client IDs, and other configuration values
   that are not credentials.

## Key Reference Files

- `README.md` — full overview, workflow, and platform notes
- `ARCHITECTURE.md` — topology and component placement
- `CLOUD_DEPLOYMENT_MATRIX.md` — Cloud-specific deployment model
- `DEPLOYMENT_ROLE_MATRIX.md` — cross-platform role placement
- `credentials.example` — credentials file template
- `skills/shared/app_registry.json` — Splunkbase IDs and app metadata
