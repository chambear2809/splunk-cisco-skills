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
| `splunk-enterprise-host-setup` | Supported | Supported | Supported | None | None | None | Linux host bootstrap workflow for self-managed Splunk Enterprise search tiers, indexers, cluster managers, SHC members, and heavy forwarders. |
| `splunk-itsi-setup` | Required | None | None | None | None | None | Premium search-tier app for ITSI dashboards and service analytics. |
| `splunk-ai-assistant-setup` | Required | None | None | None | None | None | Search-tier AI assistant app with cloud-backed inference, app UI settings, and KV Store-backed local chat state. |
| `splunk-mcp-server-setup` | Required | None | None | None | None | None | Search-tier MCP service app with custom REST handlers, KV Store-backed tool metadata, encrypted token issuance, and optional local policy overlays. |
| `splunk-stream-setup` | Required | Supported | Required | Supported | None | HF or UF | Split-package Stream deployment: search-tier UI, forwarder-side capture, and optional indexer knowledge objects. |
| `cisco-spaces-setup` | Supported | None | Supported | None | None | None | Cisco Spaces firehose collector app with UCC REST handlers for stream configuration and activation token encryption. |
| `cisco-scan-setup` | Required | None | None | None | None | None | Search-head-only catalog and management app. No data ingestion — provides product catalog UI, ecosystem intelligence, and Splunkbase analytics. |

## App And Package Placement

| App / Package | Skill | Search Tier | Indexer | Heavy Forwarder | Universal Forwarder | External Collector |
| --- | --- | --- | --- | --- | --- | --- |
| `TA_cisco_catalyst` | `cisco-catalyst-ta-setup` | Supported | None | Supported | None | None |
| `cisco_dc_networking_app_for_splunk` | `cisco-dc-networking-setup` | Supported | None | Supported | None | None |
| `cisco-catalyst-app` | `cisco-enterprise-networking-setup` | Required | None | None | None | None |
| `splunk_app_stream_ipfix_cisco_hsl` | `cisco-catalyst-enhanced-netflow-setup` | None | None | Supported | Supported | None |
| `CiscoSecurityCloud` | `cisco-security-cloud-setup` | Supported | None | Supported | None | None |
| `cisco-cloud-security` | `cisco-secure-access-setup` | Supported | None | Supported | None | None |
| `Splunk_TA_Cisco_Intersight` | `cisco-intersight-setup` | Supported | None | Supported | None | None |
| `Splunk_TA_AppDynamics` | `cisco-appdynamics-setup` | Supported | None | Supported | None | None |
| `Splunk_TA_cisco_meraki` | `cisco-meraki-ta-setup` | Supported | None | Supported | None | None |
| `splunk_app_stream` | `splunk-stream-setup` | Required | None | None | None | None |
| `Splunk_TA_stream` | `splunk-stream-setup` | None | None | Required | Supported | None |
| `Splunk_TA_stream_wire_data` | `splunk-stream-setup` | Supported | Required | Supported | None | None |
| `ta_cisco_thousandeyes` | `cisco-thousandeyes-setup` | Supported | None | Supported | None | None |
| `SA-ITOA` | `splunk-itsi-setup` | Required | None | None | None | None |
| `Splunk_AI_Assistant_Cloud` | `splunk-ai-assistant-setup` | Required | None | None | None | None |
| `Splunk_MCP_Server` | `splunk-mcp-server-setup` | Required | None | None | None | None |
| `ta_cisco_spaces` | `cisco-spaces-setup` | Supported | None | Supported | None | None |
| `splunk-cisco-app-navigator` | `cisco-scan-setup` | Required | None | None | None | None |

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
