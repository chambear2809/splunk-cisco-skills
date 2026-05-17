# Splunk and Cisco Skills

This repository is a working library of Cursor, Codex, and Claude Code agent
skills, MCP tooling, intake templates, reference docs, and shell automation for
planning, rendering, installing, configuring, validating, and handing off Splunk
Platform, Splunk Cloud, Splunk Observability Cloud, Cisco, and adjacent
operational integrations.

The catalog covers Cisco product onboarding, Splunk apps and TAs, Enterprise
Security and the broader Splunk security portfolio, ITSI, SOAR, On-Call,
Observability Cloud integrations, AI Agent Monitoring, Database Monitoring,
dashboards, detectors, OpenTelemetry collectors, Kubernetes APM
auto-instrumentation, Browser RUM and Session Replay, AWS, ThousandEyes,
Galileo, and OTLP integrations, HEC, ACS allowlists, PKI, SmartStore,
federated search,
workload management, Monitoring Console, license management, indexer clusters,
Edge Processor, Stream, Splunk Connect for OTLP, SC4S, SC4SNMP, Universal
Forwarders, Linux Splunk Enterprise hosts, self-managed Kubernetes runtimes, and
external-collector topologies.
Most workflows are render-first and validation-heavy, with explicit apply
phases and secret-file guardrails for production changes.

## Start Here

This repo is meant to be used by operators and agents. Most workflows follow
the same safe order: choose a skill, collect non-secret inputs, run a help or
dry-run command, render or apply only the requested change, then validate.

For a scannable operator view of every skill, start with
[`SKILL_UX_CATALOG.md`](SKILL_UX_CATALOG.md). It lists each skill's purpose, the
best first file to open, a safe `--help` command, the validation command, and
the deeper docs to read next.

## Quick Start

Run commands from the repository root unless a skill says otherwise.

1. Configure your local target credentials:

   ```bash
   bash skills/shared/scripts/setup_credentials.sh
   ```

   The generated `credentials` file is gitignored. Keep passwords, API tokens,
   and client secrets in `credentials` or separate secret files, not in chat or
   command-line arguments.

2. Choose the workflow:

   ```bash
   rg "Duo|ACI|HEC|OTel|Enterprise Security|Data Manager" SKILL_UX_CATALOG.md skills/*/SKILL.md
   ```

   Or open [`SKILL_UX_CATALOG.md`](SKILL_UX_CATALOG.md) and search by product,
   app, data source, or task.

3. Read the skill entry point:

   ```bash
   sed -n '1,180p' skills/<skill-name>/SKILL.md
   ```

4. Inspect the safe first command before changing anything:

   ```bash
   bash skills/<skill-name>/scripts/setup.sh --help
   ```

   This is the common pattern, but not every skill uses the same entrypoint.
   Use the exact safe first command shown in
   [`SKILL_UX_CATALOG.md`](SKILL_UX_CATALOG.md) for the selected skill.

5. Run a dry run, render, or preflight phase when the skill supports it:

   ```bash
   bash skills/cisco-product-setup/scripts/setup.sh \
     --product "Cisco ACI" \
     --dry-run
   ```

6. Run the setup phase, then validate:

   ```bash
   bash skills/<skill-name>/scripts/validate.sh
   ```

   Some skills use a Python validator, a status command, or a documented manual
   validation path instead. Use the catalog's `Validation` column when it
   differs from the common `validate.sh` pattern.

## Choose A Workflow

| Goal | Start with | First useful command |
|------|------------|----------------------|
| I know a Cisco product but not the Splunk app or TA | [cisco-product-setup](skills/cisco-product-setup/) | Run `bash skills/cisco-product-setup/scripts/setup.sh --product "Cisco ACI" --dry-run` |
| I already know the Splunkbase app or local package | [splunk-app-install](skills/splunk-app-install/) | Run `bash skills/splunk-app-install/scripts/install_app.sh --help` |
| I need Splunk Enterprise or Universal Forwarder on hosts | [splunk-enterprise-host-setup](skills/splunk-enterprise-host-setup/) or [splunk-universal-forwarder-setup](skills/splunk-universal-forwarder-setup/) | Run `bash skills/splunk-enterprise-host-setup/scripts/setup.sh --help` |
| I need Splunk Enterprise on Kubernetes | [splunk-enterprise-kubernetes-setup](skills/splunk-enterprise-kubernetes-setup/) | Run `bash skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh --help` |
| I need Splunk Cloud app installs, indexes, restarts, or allowlists | [splunk-app-install](skills/splunk-app-install/), [splunk-hec-service-setup](skills/splunk-hec-service-setup/), or [splunk-cloud-acs-allowlist-setup](skills/splunk-cloud-acs-allowlist-setup/) | Run `bash skills/splunk-cloud-acs-allowlist-setup/scripts/setup.sh --help` |
| I need Enterprise Security, SOAR, ARI, Attack Analyzer, UBA, or security routing | [splunk-security-portfolio-setup](skills/splunk-security-portfolio-setup/) | Run `bash skills/splunk-security-portfolio-setup/scripts/setup.sh --help` |
| I need Splunk Observability Cloud collection, APM, RUM, DBMon, AWS, Azure, or GCP | Search the `splunk-observability-*` skills | Run `rg "AWS|RUM|DBMon|OTel|Kubernetes" SKILL_UX_CATALOG.md` |
| I need syslog, SNMP, Stream, OTLP, Edge Processor, or other external collection | [splunk-connect-for-syslog-setup](skills/splunk-connect-for-syslog-setup/), [splunk-connect-for-snmp-setup](skills/splunk-connect-for-snmp-setup/), [splunk-connect-for-otlp-setup](skills/splunk-connect-for-otlp-setup/), or [splunk-edge-processor-setup](skills/splunk-edge-processor-setup/) | Run `rg "SC4S|SC4SNMP|OTLP|Edge Processor" SKILL_UX_CATALOG.md` |
| I need AppDynamics product coverage | [splunk-appdynamics-setup](skills/splunk-appdynamics-setup/) | Run `bash skills/splunk-appdynamics-setup/scripts/setup.sh --help` |
| I need Galileo or Agent Control wired to Splunk | [galileo-platform-setup](skills/galileo-platform-setup/) or [galileo-agent-control-setup](skills/galileo-agent-control-setup/) | Run `bash skills/galileo-platform-setup/scripts/setup.sh --help` |
| I need a broad admin health check | [splunk-admin-doctor](skills/splunk-admin-doctor/) | Run `bash skills/splunk-admin-doctor/scripts/setup.sh --help` |

## Intake And Secrets

Many account-driven skills include `template.example`. Use it as a worksheet
for non-secret intake such as hostnames, org IDs, usernames, account names,
indexes, regions, and feature choices. If you fill it out, save the local copy
as `template.local`; those files are intended to stay out of git.

The agent should ask only for non-secret values in conversation. Secrets should
come from `credentials` or from temporary files passed to flags such as
`--password-file`, `--api-token-file`, `--secret-file`, or equivalent
skill-specific options.

Rendered plans, generated manifests, package caches, live-validation
checkpoints, and local intake files are review artifacts. They are intentionally
gitignored under paths such as `splunk-*-rendered/`, `sc4s-rendered/`,
`sc4snmp-rendered/`, `splunk-ta/`, and `template.local`. Review them locally,
apply them when appropriate, and keep them out of commits unless a skill
explicitly says an artifact is tracked.

## Agent Or Shell Usage

The repo is designed for two operating modes:

- **Agent-driven work in Cursor, Codex, or Claude Code**: ask for the outcome in
  plain language, for example `Set up Cisco ACI and show me the dry-run first`.
  The agent reads `skills/*/SKILL.md`, uses the relevant template and scripts,
  and should keep secrets out of chat.
- **Direct shell use**: run the scripts under each skill yourself. Start with
  `--help`, prefer dry-run/render/preflight phases, then run validation.

## Local CLI Access Enables Live Setup

Many skills can run in a render-only mode with just local shell and Python. If
the CLI session also has access to the target environment, the same workflows
can move past rendered plans into preflight checks, apply phases, and live
validation.

Examples of access that unlocks deeper automation:

- `kubectl` and `helm` access let Kubernetes skills inspect clusters, render
  overlays, apply manifests or Helm values, and validate running pods, services,
  custom resources, and collector pipelines.
- Docker or Podman access lets external-collector workflows prepare, run, or
  validate customer-managed runtimes such as SC4S, SC4SNMP, SOAR Automation
  Broker, or other containerized components.
- Cloud CLIs such as `aws`, `az`, and `gcloud` let cloud integration skills
  discover context, render or validate IAM and role assignments, check generated
  artifacts, and hand off supported apply commands.
- SSH access lets host-bootstrap and package-staging workflows install Splunk
  Enterprise, Universal Forwarders, or apps on remote self-managed hosts.
- Splunk Cloud ACS and search-tier REST access let cloud workflows install apps,
  create indexes, manage restarts and allowlists, configure app objects, and
  validate data.

Each skill should still advertise its first safe command and whether the next
step is render-only, preflight, apply, or validation. See
[`SKILL_REQUIREMENTS.md`](SKILL_REQUIREMENTS.md) for the per-skill software and
live-access matrix.

The automation supports two Splunk administration paths:

- **Splunk Enterprise**: direct Splunk REST API access on port `8089`, with SSH
  staging as a fallback for remote app package installs.
- **Splunk Cloud**: Admin Config Service (ACS) for app installs, index
  management, and restarts, plus search-tier REST API access on port `8089` for
  TA-specific account and input configuration after the app is installed.

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
   Nexus, Intersight, Isovalent, NVIDIA GPU, Cisco AI Pod, ThousandEyes, and
   Galileo sources into Splunk Observability Cloud; and build reviewed
   Observability dashboard, detector, alert routing, and Splunk On-Call
   artifacts.
7. **Validation**: confirm the app is installed, the expected objects exist, and
   Splunk is actually receiving data.

Most of the repo follows the same Agent Skills pattern:

- `SKILL.md` uses Agent Skills frontmatter (`name` matching the directory and
  a <=1024-character `description` with a clear `Use when` trigger), then keeps
  run-critical instructions concise enough for progressive disclosure.
- `template.example` is present in account-driven skills as a non-secret intake
  worksheet that admins can copy to `template.local` before gathering account
  details.
- `reference.md` and `references/` contain vendor-specific details such as
  input families, account fields, app behavior, and longer runbooks.
- `scripts/` contains the actual shell and Python automation.
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
| `splunk-appdynamics-setup` | AppDynamics suite router | Route AppDynamics requests, enforce taxonomy coverage, orchestrate child skills, and emit doctor reports for SaaS, On-Premises, release/reference, product-announcement, API, security, AI, SAP, and Splunk Platform paths |
| `splunk-appdynamics-platform-setup` | AppDynamics On-Premises / Virtual Appliance | Render On-Premises overview, release/reference, deployment planning, platform quickstart, Enterprise Console, Controller, Events Service, EUM Server, Synthetic Server, HA, upgrade, and secure platform runbooks |
| `splunk-appdynamics-controller-admin-setup` | AppDynamics Controller administration | Configure and validate API clients, OAuth, users, groups, roles, SAML, LDAP, permissions, licensing, license rules, sensitive data controls, and tenant admin plans |
| `splunk-appdynamics-agent-management-setup` | Smart Agent / Agent Management | Render Smart Agent remote install, upgrade, rollback, software download/package validation, and managed .NET, Database, Java, Machine, and Node.js agent plans |
| `splunk-appdynamics-apm-setup` | AppDynamics APM | Configure and validate business applications, tiers, nodes, business transactions, endpoints, remote services, information points, snapshots, metrics, app-server snippets, serverless monitoring, and Splunk AppDynamics for OpenTelemetry |
| `splunk-appdynamics-k8s-cluster-agent-setup` | AppDynamics Cluster Agent | Render Cluster Agent, Kubernetes auto-instrumentation, Splunk OTel Collector, and workload rollout validation assets |
| `splunk-appdynamics-infrastructure-visibility-setup` | AppDynamics Infrastructure Visibility | Render Machine Agent, Server Visibility, Network Visibility, Docker/container visibility, service availability, tags, GPU monitoring, Prometheus extension, and infrastructure health rules |
| `splunk-appdynamics-database-visibility-setup` | AppDynamics Database Visibility | Render Database Agent readiness, redacted Database Visibility API collector payloads, and DB server/node/event validation |
| `splunk-appdynamics-analytics-setup` | AppDynamics Analytics | Render Transaction, Log, Browser, Mobile, Synthetic, IoT/Connected Devices Analytics, ADQL, Events API schemas, publish, and query validation |
| `splunk-appdynamics-eum-setup` | AppDynamics EUM / RUM | Render Browser RUM, Mobile RUM, IoT RUM, app keys, JS injection, mobile snippets, Browser and Mobile Session Replay, source maps, and beacon validation |
| `splunk-appdynamics-synthetic-monitoring-setup` | AppDynamics Synthetic Monitoring | Render Browser Synthetic, Synthetic API Monitoring, hosted and private agents, PSA Docker/Kubernetes/Minikube assets, Shepherd URLs, and run validation |
| `splunk-appdynamics-log-observer-connect-setup` | AppDynamics Log Observer Connect | Render LOC setup, legacy Splunk integration detection/disablement, Splunk service-account handoffs, and deep-link validation |
| `splunk-appdynamics-alerting-content-setup` | AppDynamics alerting content | Render health rules, schedules, policies, actions, email digests, suppression, import/export, rollback, anomaly detection, AIML baselines, automated diagnostics, and validation |
| `splunk-appdynamics-dashboards-reports-setup` | AppDynamics dashboards and reports | Render custom dashboards, Dash Studio handoffs, reports, scheduled reports, War Rooms, and dashboard/report validation |
| `splunk-appdynamics-thousandeyes-integration-setup` | AppDynamics + ThousandEyes integration | Render AppDynamics TE token, Dash Studio, EUM metrics, native TE integration, TE API assets, custom webhook, and administration runbooks |
| `splunk-appdynamics-tags-extensions-setup` | AppDynamics tags and extensions | Render Custom Tag APIs, tag enablement, Integration Modules, extensions, Machine Agent custom metrics, and external integration runbooks |
| `splunk-appdynamics-security-ai-setup` | AppDynamics security and AI | Render Application Security Monitoring, Secure Application policies/APIs, Secure Application for OTel Java, Observability for AI, GenAI, GPU, and Cisco AI Pod handoffs |
| `splunk-appdynamics-sap-agent-setup` | AppDynamics SAP Agent | Render SAP Agent, ABAP Agent, local and gateway HTTP SDK, SNP CrystalBridge, BiQ Collector, NetWeaver transports, authorization, release-note, compatibility, and validation runbooks |
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
| `splunk-ai-ml-toolkit-setup` | Splunk AI Toolkit / MLTK + PSC + DSDL | Install, render, validate, and audit Splunk-owned AI/ML workflows beyond AI Assistant, including AI Toolkit, Python for Scientific Computing, DSDL runtime handoffs, anomaly workflows, LLM `ai` command readiness, and legacy anomaly migration |
| `splunk-mcp-server-setup` | `Splunk_MCP_Server` | Install and configure Splunk MCP Server settings, tokens, and shared Cursor/Codex/Claude Code bridge bundles |
| `splunk-admin-doctor` | Splunk Cloud and Enterprise admin health | Diagnose full admin-domain coverage, render doctor/fix-plan reports, create safe fix packets or handoffs, and run checkpointed live validation sweeps |
| `splunk-data-source-readiness-doctor` | ES/ITSI/ARI/CIM/OCSF/dashboard data usability | Score whether onboarded data is ready for Enterprise Security, ITSI, and ARI by checking expected indexes, sourcetypes, macros, sample events, CIM tags/eventtypes, data-model acceleration, OCSF transforms, dashboard population, and fix handoffs |
| `splunk-spl2-pipeline-kit` | Shared SPL2 pipeline authoring for IP and EP | Render and lint reusable SPL2 templates for routing, redact, sample, metrics, OCSF, decrypt, stats, S3, custom templates, SPL-to-SPL2 review, and PCRE2 compatibility across Ingest Processor and Edge Processor |
| `splunk-ingest-processor-setup` | Splunk Cloud Platform Ingest Processor | Render, doctor, status-check, and validate Ingest Processor readiness, source types, destinations, SPL2 pipelines, lifecycle handoffs, monitoring, queues, Usage Summary, S3 archive, OCSF, decrypt, metrics, and downstream data-readiness handoffs without private API CRUD claims |
| `splunk-cloud-data-manager-setup` | Splunk Cloud Platform Data Manager | Render, doctor, validate, and safely apply supported Data Manager-generated AWS CloudFormation/StackSet, Azure ARM, and GCP Terraform artifacts; covers AWS, Azure, GCP, and CrowdStrike onboarding, HEC/index readiness, source catalogs, migration guardrails, and UI handoffs without private Data Manager API or Terraform CRUD claims |
| `splunk-db-connect-setup` | Splunk DB Connect (`splunk_app_db_connect`) | Render, preflight, validate, and hand off production-safe DB Connect JDBC ingestion, lookup, enrichment, and export assets with Java, driver, topology, secret-file, and Cloud guardrails |
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
| `galileo-platform-setup` | Galileo SaaS/Enterprise platform -> Splunk Platform and Splunk Observability Cloud | Render, validate, and optionally apply Galileo readiness, object lifecycle provisioning for projects/log streams/datasets/prompts/experiments/metrics/Protect stages/Agent Control targets, full feature coverage matrix for REST API/custom deployment healthchecks, auth/RBAC, SSO/OIDC/SAML, integrations, costs, Luna-2 fine-tuning/evaluation, scorers, Evaluate workflow runs, trace maintenance, annotations, feedback, Trends, run insights, multimodal logging, tags/metadata, enterprise retention/TTL/privacy, Agent Graph and console debugging views, distributed tracing, alerts, framework wrappers, MCP tool-call logging, Galileo MCP tooling, playground/sample/CI workflows, official cookbook/use-case starter examples, SDK utilities, troubleshooting, release/version compatibility, and enterprise admin handoffs, `export_records` to Splunk HEC, Observe OpenTelemetry/OpenInference snippets, Protect invoke snippets, Splunk HEC/OTLP/OTel Collector handoffs, and Observability dashboard/detector handoffs; supports `--o11y-only` to omit Splunk Platform HEC dependencies |
| `galileo-agent-control-setup` | Agent Control -> Splunk Platform and Splunk Observability Cloud | Render, validate, and optionally apply Agent Control server readiness, file-backed auth templates, controls, Python/TypeScript runtime snippets, OTel sink config, custom Splunk HEC event sink, Splunk HEC/OTel Collector handoffs, and Observability dashboard/detector handoffs |
| `splunk-observability-isovalent-integration` | Isovalent (Cilium / Hubble / Tetragon) -> Splunk Observability Cloud + Splunk Platform | Render the Splunk OTel collector overlay (seven `prometheus/isovalent_*` scrape jobs + `filter/includemetrics` + cilium-dnsproxy fix); Splunk Platform logs DEFAULT via OTel filelog receiver + hostPath mount + `extraFileLogs.filelog/tetragon` (production-validated); legacy fluentd splunk_hec behind `--legacy-fluentd-hec` (DEPRECATED); hands off Tetragon log ingestion to `cisco-security-cloud-setup` (`PRODUCT=isovalent`, sourcetype `cisco:isovalent`, index `cisco_isovalent`) |
| `splunk-observability-cisco-nexus-integration` | Cisco Nexus 9000 fabric -> Splunk Observability Cloud | Standalone reusable: clusterReceiver `cisco_os` overlay (PR #45562 multi-device + global-scrapers format, contrib v0.149.0+) with K8s Secret manifest stub for SSH credentials, dashboards (port utilization, errors, drops, CPU/memory) and detectors (interface down, packet drop rate, CPU/memory pressure). Companion to `cisco-dc-networking-setup` (Splunk Platform TA path). |
| `splunk-observability-cisco-intersight-integration` | Cisco Intersight (UCS) -> Splunk Observability Cloud | Standalone reusable: separate `intersight-otel` namespace + Secret manifest stub + Deployment + ConfigMap pointing at the Splunk OTel agent's OTLP gRPC endpoint; dashboards (UCS power/thermal/fan/network/alarms/advisories/VM count) and detectors (alarm spike, security advisory delta, host temp/power, fan failure). Companion to `cisco-intersight-setup` (Splunk Platform TA path). |
| `splunk-observability-nvidia-gpu-integration` | NVIDIA GPUs (DCGM Exporter) -> Splunk Observability Cloud | Standalone reusable: `receiver_creator/dcgm-cisco` (parameterized; explicitly NOT `receiver_creator/nvidia` to avoid collision with chart autodetect); dual-label DCGM discovery (`app` + `app.kubernetes.io/name`); default unfiltered `metrics/nvidia-metrics` pipeline; `--enable-dcgm-pod-labels` patch (env-var + RBAC + SA-token + kubelet mount) for the well-known GPU Operator pod-label gap. Works for any GPU cluster (NVIDIA DGX, AI Pod, generic K8s + GPUs). |
| `splunk-observability-cisco-ai-pod-integration` | Cisco AI Pod (UCS + Nexus + NVIDIA GPUs + NIM/vLLM + storage) -> Splunk Observability Cloud | Umbrella that composes Nexus + Intersight + NVIDIA GPU components via subprocess + Python deep-merge AND adds NIM scrape (TWO modes: `receiver_creator` simple vs `endpoints` precise + `rbac.customRules` patch), vLLM, Milvus, NetApp Trident (port 8001), Pure Portworx (17001+17018), Redfish exporter (user-supplied), `k8s_attributes/nim` for `model_name` extraction, dual-pipeline filtering pattern, OpenShift defaults (kubeletstats `insecure_skip_verify`, certmanager off, cloudProvider empty), `--workshop-mode` multi-tenant.sh, OpenShift SCC helper. Mirrors `signalfx/splunk-opentelemetry-examples/collector/cisco-ai-ready-pods` + production-validated atl-ocp2 OpenShift cluster. |
| `splunk-observability-aws-integration` | AWS -> Splunk Observability Cloud | Standalone reusable: render, apply, validate, discover, and diagnose the `AWSCloudWatch` integration end-to-end across polling, Splunk-managed Metric Streams, AWS-managed Metric Streams, and Terraform. Emits IAM policy JSON, regional or StackSets CloudFormation stubs, Splunk-side Terraform, API payloads, drift reports, and handoffs for AWS logs, Lambda APM, dashboards, detectors, and EC2/EKS host telemetry. |
| `splunk-observability-azure-integration` | Azure -> Splunk Observability Cloud | Render, apply, validate, discover, and diagnose the Azure Monitor integration. REST type=Azure; SP tenantId+appId+secretKey via chmod-600 files (appId/secretKey redacted on GET); azureEnvironment AZURE or AZURE_US_GOVERNMENT; per-subscription list; ~80-service enum + additionalServices; pollRate 60–600s; Terraform signalfx_azure_integration; Azure CLI SP creation + role scripts; Bicep role-assignment; handoffs for Splunkbase 3110 (logs), 4882 (dashboards), AKS OTel collector. |
| `splunk-observability-gcp-integration` | GCP -> Splunk Observability Cloud | Render, apply, validate, discover, and diagnose the GCP Cloud Monitoring integration. REST type=GCP; SERVICE_ACCOUNT_KEY or WORKLOAD_IDENTITY_FEDERATION authMethod; projectKey redacted on GET; 32-service enum; pollRate 60–600s; Terraform signalfx_gcp_integration; gcloud SA creation + IAM binding scripts; WIF realm-to-principal map; handoffs for Splunkbase 3088 (GCP logs), GKE OTel collector. |
| `splunk-observability-aws-lambda-apm-setup` | AWS Lambda -> Splunk Observability Cloud APM | Render, validate, and optionally apply Splunk OTel Lambda layer (`signalfx/splunk-otel-lambda`, beta, publisher `254067382080`) APM instrumentation. Node.js/Python/Java runtimes, x86_64/arm64, exec-wrapper wiring, Secrets Manager/SSM token delivery, vendor/ADOT conflict detection, Terraform/CloudFormation/AWS CLI variants, rollback, doctor. |
| `splunk-observability-dashboard-builder` | Splunk Observability Cloud dashboards | Render, validate, and optionally apply classic Observability dashboard groups, charts, and dashboards from natural-language, JSON, or YAML specs |
| `splunk-observability-deep-native-workflows` | Splunk Observability Cloud deep native workflows | Render and validate full native product workflow packets for modern dashboards, APM service maps/service views/business transactions/trace waterfalls/profiling, RUM replay/errors/URL grouping/mobile RUM, DBMon query/explain-plan triage, Synthetic waterfall artifacts, SLO API payloads, Infrastructure/Kubernetes/Network Explorer, Related Content, AI Assistant, modern logs charts, and Observability Cloud Mobile app handoffs; emits API-vs-UI coverage reports, deeplinks, apply plans, and downstream skill handoffs |
| `splunk-observability-native-ops` | Splunk Observability Cloud native operations | Render, validate, and optionally apply supported native Observability operations for detectors, alert routing, Synthetics, APM, RUM, logs, and On-Call handoffs |
| `splunk-oncall-setup` | Splunk On-Call (formerly VictorOps) | Render, validate, and apply On-Call teams, users, rotations, escalation policies, routing keys, incidents, REST/email alert payloads, and Splunk-side companion app handoffs |
| `splunk-stream-setup` | Splunk Stream stack | Install and configure Splunk Stream components |
| `splunk-connect-for-syslog-setup` | SC4S external collector | Prepare Splunk HEC/indexes and render or apply Docker, Podman, systemd, or Helm assets for Splunk Connect for Syslog |
| `splunk-connect-for-snmp-setup` | SC4SNMP external collector | Prepare Splunk HEC/indexes and render or apply Docker Compose or Helm assets for Splunk Connect for SNMP |
| `splunk-license-manager-setup` | Splunk Enterprise license manager / peers / pools / groups / messages | Install licenses, switch groups, configure peers, allocate pools, audit usage and violations, validate version compatibility |
| `splunk-soar-setup` | `splunk_soar-unpriv` (single + cluster) + `splunk_app_soar` (6361) + Splunk App for SOAR Export (3411) + Splunk SOAR Automation Broker | Install SOAR On-prem (single + cluster with external PG/GlusterFS/Elasticsearch), help with SOAR Cloud onboarding, install Automation Broker on Docker/Podman, install Splunk-side SOAR apps, ready ES integration, backup/restore |
| `splunk-edge-processor-setup` | Splunk Edge Processor instances + cloud / Enterprise control plane | Add EP control-plane object, install instances on Linux (systemd or not), scale to multi-instance, manage source types / destinations / SPL2 pipelines, apply pipelines, validate health |
| `splunk-indexer-cluster-setup` | Splunk Enterprise indexer cluster (single-site, multisite, redundant managers) | Bootstrap manager(s) / peers / SHs, manage cluster bundle (validate / apply / rollback), rolling restart (default / searchable / forced), peer offline (fast / enforce-counts), maintenance mode, single-site to multisite migration, manager replacement |
| `splunk-search-head-cluster-setup` | Splunk Enterprise Search Head Cluster | Plan, render, bootstrap, and operate an SHC: deployer config push, member `server.conf` generation, sequenced bootstrap, rolling restarts, captain transfer, KV Store replication, member add / decommission / remove, migration, and failure mode runbooks |
| `splunk-deployment-server-setup` | Splunk Enterprise Deployment Server runtime | Bootstrap DS, tune `phoneHomeIntervalInSecs` for large UF fleets, REST fleet inspection, HA pair, cascading DS guard, mass re-targeting, staged rollout, and explicit `filterType` rendering |
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

## Agent Skills Specification Compliance

This repository intentionally follows the public
[Agent Skills specification](https://agentskills.io/specification) and its
creator guidance for
[best practices](https://agentskills.io/skill-creation/best-practices) and
[evaluating skills](https://agentskills.io/skill-creation/evaluating-skills).
Every skill is expected to keep the required `SKILL.md` contract, concise
trigger metadata, progressive-disclosure structure, script-backed repeatable
workflows, and validation coverage.

Compliance is enforced in pre-commit and CI through:

- `tests/check_skill_frontmatter.py` for the Agent Skills frontmatter,
  description, naming, and progressive-disclosure limits.
- `tests/check_repo_readiness.py` for catalog parity, agent command links,
  local artifact guardrails, and this specification callout.
- Required GitHub branch protection on `main` for the `validation`,
  `python-tests`, `bats-tests`, and `shellcheck` jobs.

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
│   ├── galileo-agent-control-setup/
│   ├── galileo-platform-setup/
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
│   ├── splunk-data-source-readiness-doctor/
│   ├── splunk-db-connect-setup/
│   ├── splunk-deployment-server-setup/
│   ├── splunk-edge-processor-setup/
│   ├── splunk-ingest-processor-setup/
│   ├── splunk-spl2-pipeline-kit/
│   ├── splunk-enterprise-host-setup/
│   ├── splunk-enterprise-kubernetes-setup/
│   ├── splunk-enterprise-public-exposure-hardening/
│   ├── splunk-enterprise-security-config/
│   ├── splunk-enterprise-security-install/
│   ├── splunk-federated-search-setup/
│   ├── splunk-hec-service-setup/
│   ├── splunk-index-lifecycle-smartstore-setup/
│   ├── splunk-indexer-cluster-setup/
│   ├── splunk-itsi-config/
│   ├── splunk-itsi-setup/
│   ├── splunk-license-manager-setup/
│   ├── splunk-mcp-server-setup/
│   ├── splunk-monitoring-console-setup/
│   ├── splunk-observability-ai-agent-monitoring-setup/
│   ├── splunk-observability-aws-integration/
│   ├── splunk-observability-aws-lambda-apm-setup/
│   ├── splunk-observability-azure-integration/
│   ├── splunk-observability-cisco-ai-pod-integration/
│   ├── splunk-observability-cisco-intersight-integration/
│   ├── splunk-observability-cisco-nexus-integration/
│   ├── splunk-observability-cloud-integration-setup/
│   ├── splunk-observability-dashboard-builder/
│   ├── splunk-observability-database-monitoring-setup/
│   ├── splunk-observability-deep-native-workflows/
│   ├── splunk-observability-gcp-integration/
│   ├── splunk-observability-isovalent-integration/
│   ├── splunk-observability-k8s-auto-instrumentation-setup/
│   ├── splunk-observability-k8s-frontend-rum-setup/
│   ├── splunk-observability-native-ops/
│   ├── splunk-observability-nvidia-gpu-integration/
│   ├── splunk-observability-otel-collector-setup/
│   ├── splunk-observability-thousandeyes-integration/
│   ├── splunk-oncall-setup/
│   ├── splunk-platform-pki-setup/
│   ├── splunk-platform-restart-orchestrator/
│   ├── splunk-search-head-cluster-setup/
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

Use these repo-level docs when choosing a path:

| Question | Read |
|----------|------|
| Which skill should I use first? | [`SKILL_UX_CATALOG.md`](SKILL_UX_CATALOG.md) |
| What tools and access does this skill need? | [`SKILL_REQUIREMENTS.md`](SKILL_REQUIREMENTS.md) |
| Where should this app or workflow run? | [`DEPLOYMENT_ROLE_MATRIX.md`](DEPLOYMENT_ROLE_MATRIX.md) |
| How does Splunk Cloud differ from Enterprise? | [`CLOUD_DEPLOYMENT_MATRIX.md`](CLOUD_DEPLOYMENT_MATRIX.md) |
| How is the repo organized internally? | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| How do I demo the workflow? | [`DEMO_SCRIPTS.md`](DEMO_SCRIPTS.md) |
| How do I contribute safely? | [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`SECURITY.md`](SECURITY.md) |

If you want to understand a specific skill, read these files in order:

1. `skills/<skill>/SKILL.md`
2. `skills/<skill>/reference.md` if present
3. `skills/<skill>/scripts/*`

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
dry-runs/lists, AppDynamics render/doctor/rollback coverage plans, and
allowlisted render/preflight/status/validate/dry-run previews. They can run
with explicit client confirmation. Plans are single-use:
each plan hash is consumed when it executes, and plan hashes expire after one
hour by default (`MCP_PLAN_TTL_SECONDS`; set `0` to disable expiry). To allow
mutating setup, install, or configure scripts, start the MCP server process with:

```bash
SPLUNK_SKILLS_MCP_ALLOW_MUTATION=1 python3 agent/run-splunk-cisco-skills-mcp.py
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
- Docker or Podman access for customer-managed container runtimes
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
`splunk-observability-aws-lambda-apm-setup` owns the Splunk OTel Lambda layer
lifecycle for APM/tracing of AWS Lambda functions and is the fulfillment of
the `handoffs.lambda_apm` stub from the AWS integration skill.
`splunk-observability-dashboard-builder` is separate from runtime placement: it
renders and validates native Observability Cloud dashboard API payloads and can
apply them only when explicitly requested.
`splunk-observability-deep-native-workflows` covers UI-aware native product
journeys that are deeper than detector/dashboard object lifecycle: modern
dashboard composition, APM service maps/service views/business
transactions/trace waterfalls/profiling, RUM replay/errors/URL grouping/mobile
RUM, DBMon explain-plan triage, Synthetic waterfalls, SLO payloads,
Infrastructure/Kubernetes/Network Explorer, Related Content, AI Assistant, logs
charts, and the Observability Cloud Mobile app. It emits coverage reports,
deeplinks, API action plans, and downstream handoffs instead of claiming runtime
placement.
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
`splunk-observability-aws-lambda-apm-setup`,
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
