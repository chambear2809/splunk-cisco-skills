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
| `splunk-app-install` Webex add-on | 8365 | ACS Splunkbase | Configure Webex REST API inputs in the add-on UI or vendor docs | Install-only route from `cisco-product-setup`; product-specific input automation is not implemented in this repo. |
| `splunk-app-install` Cisco UCS add-on | 2731 | ACS Splunkbase | Configure UCS Manager inputs in the add-on UI or supported Splunk docs | Install-only route from `cisco-product-setup`; product-specific input automation is not implemented in this repo. |
| `splunk-app-install` Cisco ESA add-on | 1761 | ACS Splunkbase | Configure ESA log forwarding or SC4S collection outside this repo | Install-only route from `cisco-product-setup`; product-specific input automation is not implemented in this repo. |
| `splunk-app-install` Cisco WSA add-on | 1747 | ACS Splunkbase | Configure WSA log forwarding or SC4S collection outside this repo | Install-only route from `cisco-product-setup`; product-specific input automation is not implemented in this repo. |
| `splunk-app-install` Cisco Talos intelligence | 7557 | ACS Splunkbase for supported ES Cloud stacks | Finish setup in the supported Enterprise Security / SOAR workflow | Install-only route from `cisco-product-setup`; Splunk documents this app for Splunk Enterprise Security Cloud. |
| `cisco-meraki-ta-setup` | 5580 | ACS Splunkbase | REST via custom account/input handlers | Cisco EULA license-ack required. Dashboard macro alignment after install. |
| `cisco-intersight-setup` | 7828 | ACS Splunkbase | REST via custom account/input handlers | Cisco EULA license-ack required. Index creation uses ACS. |
| `cisco-dc-networking-setup` | 7777 | ACS Splunkbase | REST via custom account/input handlers | Cisco EULA license-ack required. Index creation uses ACS. |
| `cisco-enterprise-networking-setup` | 7539 | ACS Splunkbase | REST for macros/saved searches/datamodel settings | Cisco EULA license-ack required. Visualization app only; installer auto-adds required TA `7538` when missing. Optional Enhanced Netflow add-on `6872` should be offered separately when users want extra NetFlow dashboards. |
| `cisco-product-setup` | N/A | Delegates to the routed Cisco app install path for the resolved product | Delegates to the routed Cisco setup skill after resolving the SCAN catalog product name | Top-level Cisco product orchestrator. Uses the packaged SCAN catalog plus local overrides to resolve a product name, classify gaps, and run the matching setup workflow. |
| `cisco-thousandeyes-setup` | 7719 | ACS Splunkbase | REST for OAuth account, HEC-based streaming inputs, polling inputs | Requires HEC token. OAuth device code flow for auth. ITSI integration optional. |
| `splunk-itsi-setup` | 1841 | ACS Splunkbase | No post-install REST config needed | Premium product; requires ITSI license. Enables ThousandEyes ITSI integration. |
| `splunk-enterprise-security-install` | 263 | Splunk Support coordinated ES service workflow | `splunk-enterprise-security-config` validation plus Splunk Support for Cloud-managed indexer-side changes | Premium SIEM product. On-prem installs prefer the local ES package when present, fall back to Splunkbase app 263, then run essinstall. |
| `splunk-enterprise-security-config` | N/A | No additional app install; requires ES already provisioned | REST validation and supported search-tier settings; Splunk Cloud indexer-side changes remain support-managed | Operational ES configuration workflow for indexes, roles, CIM data models, enrichment, detections, risk, and validation. |
| `splunk-ai-assistant-setup` | 7245 | ACS Splunkbase | App-local settings and activation happen in the app UI | Search-tier app only. Splunk Cloud installs stay on the public Splunkbase path; Enterprise uses cloud-connected activation after install. |
| `splunk-mcp-server-setup` | N/A | ACS private app upload or vetted local package | REST for mcp.conf settings, token policy, and rate limits; local JSON policy overlays remain package-content concerns | Search-tier MCP endpoint for Splunk with encrypted token issuance and shared Cursor/Codex/Claude Code bridge rendering. |
| `splunk-agent-management-setup` | N/A | Not a Splunk Cloud install path; renders customer-managed Agent Management assets | Rendered serverclass.conf, deployment apps, and deploymentclient.conf for Enterprise deployment-server style workflows | Splunk Enterprise 10.x Agent Management workflow for full Enterprise instances, forwarders, and OTel fleet overview. |
| `splunk-workload-management-setup` | N/A | Not a Splunk Cloud install path; configures self-managed Enterprise Workload Management | Rendered workload_pools.conf, workload_rules.conf, workload_policy.conf, and local reload helpers | Linux-only Enterprise workflow for cgroups-backed workload pools, workload rules, and admission-rule guardrails. |
| `splunk-hec-service-setup` | N/A | No Splunk Cloud app install; Splunk Cloud HEC tokens are managed through ACS | Enterprise inputs.conf rendering or Splunk Cloud ACS HEC token payloads and helper commands | Reusable HEC platform service workflow for allowed indexes, default source/sourcetype, TLS, and ACK-aware token handling. |
| `splunk-federated-search-setup` | N/A | No Splunk Cloud app install; Federated Search is native platform configuration | Rendered self-managed Enterprise federated.conf/indexes.conf assets; Splunk Cloud deployments should use supported Federated Search UI or API workflows | Splunk-to-Splunk standard or transparent federated provider workflow with standard-mode federated index and SHC replication guardrails. |
| `splunk-index-lifecycle-smartstore-setup` | N/A | Not a Splunk Cloud install path; SmartStore is managed by Splunk Cloud | Rendered self-managed Enterprise SmartStore indexes.conf, server.conf, and limits.conf assets for indexers or cluster managers | Self-managed index lifecycle workflow for remote volumes, retention limits, cache manager settings, remote-storage localization limits, and cluster bundle apply. |
| `splunk-monitoring-console-setup` | N/A | Not a Splunk Cloud app install; Cloud Monitoring Console is Splunk-managed | Rendered self-managed Enterprise Monitoring Console local configuration plus review-only distsearch.conf peer and group helpers | Distributed or standalone Monitoring Console workflow for auto-config, distributed search groups, forwarder monitoring, and platform alert enablement. |
| `splunk-stream-setup` search-tier app | 1809 | ACS or Splunk Cloud support workflow | Stream UI / REST on search tier | Cloud deployment is hybrid, not single-target. |
| `splunk-stream-setup` wire-data add-on | 5234 | ACS or bundled with Stream deployment | No special post-install config in normal flow | Knowledge-object support for Stream search content. |
| `splunk-stream-setup` forwarder add-on | 5238 | Manual install on HF/UF you control | Local HF files plus host forwarding config | This package runs on the heavy/universal forwarder, not the Cloud search tier. |
| `splunk-connect-for-syslog-setup` | N/A | No Splunk Cloud app install; SC4S runtime is rendered for customer-managed hosts or Kubernetes | ACS for indexes/HEC where available, search-tier REST for validation, rendered host/Helm assets for runtime | External syslog-ng collector pattern. Modeled as a workflow row rather than a Splunk app package. |
| `splunk-connect-for-snmp-setup` | N/A | No Splunk Cloud app install; SC4SNMP runtime is rendered for customer-managed Docker Compose or Kubernetes | ACS for indexes/HEC where available, search-tier REST for validation, rendered compose/Helm assets for runtime | External SNMP collector pattern. Modeled as a workflow row rather than a Splunk app package. |
| `splunk-observability-otel-collector-setup` | N/A | No Splunk Cloud app install; OTel Collector runtime is rendered for customer-managed Kubernetes clusters or Linux hosts | Rendered Helm values, Kubernetes secret helpers, Linux installer wrappers, and optional HEC token handoff scripts using file-based tokens | External OpenTelemetry Collector workflow for Observability metrics, traces, profiling, Kubernetes events, discovery, auto-instrumentation, and optional Splunk Platform HEC logs with splunk-hec-service-setup handoff helpers. |
| `splunk-observability-dashboard-builder` | N/A | No Splunk Cloud app install; renders Splunk Observability Cloud dashboard groups, charts, dashboards, and apply plans | Validate and optionally apply classic Observability dashboard API payloads; access tokens stay file-based and are never placed in chat or command arguments | Dashboard composition workflow for Observability dashboard groups, charts, variables, detector links, runbooks, rendered API payloads, and optional applies. |
| `splunk-enterprise-host-setup` | N/A | Not a Splunk Cloud install path; bootstraps customer-managed Enterprise hosts only | Local or SSH-driven Linux host bootstrap for search-tier, indexer, and heavy-forwarder roles | Enterprise runtime bootstrap workflow for standalone or single-site clustered hosts. |
| `splunk-enterprise-kubernetes-setup` | N/A | Not a Splunk Cloud install path; renders customer-managed Splunk Enterprise Kubernetes deployments | Rendered SOK Helm assets or Splunk POD cluster-config.yaml and installer helpers | Self-managed Kubernetes runtime workflow for SOK S1/C3/M4 or Splunk POD on Cisco UCS. |
| `cisco-spaces-setup` | 8485 | ACS Splunkbase | REST via UCC custom stream/input handlers | Cisco EULA license-ack required. Firehose streaming input for Cisco Spaces indoor location analytics. |

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
