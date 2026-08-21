# Cisco Data Fabric Research Ledger

Verified 2026-07-03. Prefer current product documentation over launch-date
targets, and preserve alpha/preview/activation caveats.

| Source | Coverage use |
| --- | --- |
| https://newsroom.cisco.com/c/r/newsroom/en/us/a/y2025/m09/cisco-data-fabric-transforms-machine-data-into-ai-ready-intelligence.html | Launch architecture, edge management, federation targets, Machine Data Lake, AI Toolkit, MCP, time-series model, AI Canvas, and original availability targets. |
| https://blogs.cisco.com/news/machine-data-the-next-frontier-in-ai | Cisco architecture framing, open API/federation, Machine Data Lake, open-weight model intent, and AI Canvas. |
| https://www.splunk.com/en_us/blog/platform/powering-ai-innovation-with-splunk-meet-the-cisco-data-fabric.html | Explicit architecture pillars, next-generation federation, SAL direction, Machine Data Lake, MCP, and automated field extraction. |
| https://www.splunk.com/en_us/blog/platform/the-complete-guide-to-splunk-data-management.html | Explicit statement that Data Fabric is not a single product; collection, processing, storage, governance, AFE CA, Guided Onboarding/Auto-Schematization alpha, and machine-data activation. |
| https://www.splunk.com/en_us/blog/platform/new-splunk-platform-innovations-cisco-live-2026.html | 2026 update: Machine Data Lake alpha, built-in Data Catalog, AI-powered data management, expanded federation, Agent Builder alpha/GA target, Cisco Time Series Model roadmap, and AI Canvas/Cloud Control direction. The Agent Builder alpha and Fall 2026 GA target in this blog are superseded by AI Toolkit 6.0.2 Agent Launchpad documentation; do not cite this blog for that lifecycle. |
| https://www.splunk.com/en_us/blog/leadership/turning-cisco-data-fabric-vision-into-agentic-operations-reality.html | Data, context, and action layers; indexes/MDL/federated sources; catalog, knowledge graph, business context; governance and human accountability. |
| https://www.splunk.com/en_us/blog/leadership/splunk-cisco-live-agentic-operations.html | Current architecture summary, federation target list, Machine Data Lake, Agent Builder, and Cloud Control experience. |
| https://www.splunk.com/en_us/blog/platform/unifying-your-data-with-federated-search.html | May 2026 Federated Search GA framing plus store-specific GA/CA distinctions, Splunk-native/BYO catalog, schema inference, routing, and SPL2. |
| https://www.splunk.com/en_us/blog/security/federated-analytics-analyze-data-wherever-it-resides-for-rapid-and-holistic-security-visibility.html | Federated Analytics GA and premium-add-on lifecycle, kept separate from tenant activation, same-region, topology, OCSF, and scan-entitlement requirements. |
| https://help.splunk.com/en/splunk-cloud-platform/search/federated-search/10.5.2605/welcome-to-splunk-federated-search/overview-of-the-federated-search-options-for-the-splunk-platform | Version-pinned 10.5 federation options and per-product activation/platform constraints. The page says "5" while enumerating seven; use the named list, not the erroneous count. |
| https://help.splunk.com/en/splunk-cloud-platform/search/federated-search/10.5.2605/run-federated-searches-over-amazon-s3-datasets/overview-of-federated-search-for-amazon-s3 | Current S3 connection/dataset workflows, catalogs, formats, encryption, storage classes, roles, DSU, and routing-plus-search. |
| https://help.splunk.com/en/splunk-cloud-platform/search/federated-search/10.5.2605/run-federated-searches-over-microsoft-azure-datasets/about-federated-search-for-microsoft-azure | ADLS/Blob datasets, Splunk-native catalogs, routing/search workflows, roles, and network prerequisites. |
| https://help.splunk.com/en/splunk-cloud-platform/search/federated-search/10.5.2605/run-federated-searches-over-azure-databricks-datasets/about-federated-search-for-azure-databricks | Unity Catalog, Delta Sharing, runtime, role, dataset, and SPL2 prerequisites. |
| https://help.splunk.com/en/splunk-cloud-platform/search/federated-search/10.5.2605/run-federated-searches-over-snowflake-datasets/about-federated-search-for-snowflake | Snowflake table/view federation and current 10.5 prerequisites. |
| https://help.splunk.com/en/splunk-cloud-platform/search/federated-search/10.5.2605/run-federated-searches-over-ddss-datasets/about-federated-search-for-ddss | DDSS S3-only federation, catalog crawler/sync, policies, roles, and dataset identity. |
| https://help.splunk.com/en/splunk-cloud-platform/search/federated-search/10.5.2605/ingest-and-search-amazon-security-lake-datasets/about-federated-analytics | Amazon Security Lake detection/hunting split, OCSF datasets, DSUs, region/topology, and restrictions. |
| https://help.splunk.com/en/splunk-cloud-platform/search/federated-search/10.5.2605/search-data-stored-in-amazon-s3-legacy/begin-defining-an-amazon-s3-federated-provider | Legacy S3 provider/index deprecation, 10.5 read-only state, and Data Management migration. |
| https://help.splunk.com/en/splunk-cloud-platform/search/discover-data-using-the-catalog/10.5.2605/discovering-data-for-your-investigations-using-the-catalog | Global Catalog discovery surface and rollout boundary, distinct from per-dataset catalogs. |
| https://www.splunk.com/en_us/blog/platform/general-availability-promote-in-splunk-cloud-platform.html | Promote GA for selective historical S3 ingestion into indexed Splunk. |
| https://help.splunk.com/en/data-management/ingest-data-from-cloud-sources/data-inputs-service-description/1.17/data-manager/data-inputs-service-details | Data Inputs naming and service boundary, formerly Data Manager. |
| https://help.splunk.com/en/data-management/monitor-and-troubleshoot/ingest-monitoring | Ingest Monitoring 1.2 metrics, dashboards, alerts, setup, and release notes. |
| https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/6.0.2/release-notes/whats-new-in-the-ai-toolkit | AI Toolkit 6.0.2 baseline, replacing the earlier 5.7.4 record. Verified 2026-08-20. |
| https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/6.0.2/install-and-upgrade-the-ai-toolkit/splunk-ai-toolkit-version-dependencies | Supported pairing table: AI Toolkit 6.0.2 and 6.0.1 with PSC 4.3.4 on Python 3.13, plus the clean-install caution for PSC upgrades. Verified 2026-08-20. |
| https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/6.0.2/ai-toolkit-connections-containers-and-agents/ai-toolkit-agent-launchpad | Agent Launchpad GA workflow: supported AWS regions and the per-region egress IP for the stack `apiAllowlistIP`, supported LLM and MCP providers, Agent Skills, `edit_agent_connections`, `run_agents`, `aiagent`, and the in-product run-history page. Supersedes the withdrawn 5.6.4 Agent Builder feature-preview page. Verified 2026-08-20. |
| https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/6.0.2/ai-toolkit-connections-containers-and-agents/agent-launchpad-for-on-premises-users | Splunk Enterprise path to Agent Launchpad through the Splunk Cloud Connect app. Verified 2026-08-20. |
| https://help.splunk.com/en/splunk-cloud-platform/apply-machine-learning/use-ai-toolkit/6.0.2/ai-toolkit-models/cisco-deep-time-series-model | Current CDTSM boundary with no feature-preview language, replacing the 5.7.4 "Feature preview: Cisco Deep Time Series Model" record. The 6.0.2 feature-preview slug redirects here. Verified 2026-08-20. |
| https://help.splunk.com/en/splunk-enterprise/apply-machine-learning/use-ai-toolkit/6.0.2/ai-toolkit-models/cisco-deep-time-series-model-on--premises-installation | Splunk Enterprise self-hosted CDTSM model service requirement. Verified 2026-08-20. |
| https://huggingface.co/cisco-ai/cisco-time-series-model-1.0 | Available Cisco Time Series Model 1.0 model card, Apache-2.0 license, package/self-hosting instructions, and distinction from the earlier preview. |
| https://help.splunk.com/en/splunk-enterprise/mcp-server-for-splunk-platform/1.1/about-mcp-server-for-splunk-platform | MCP Server GA status, RBAC, encrypted tokens, tool management, and legacy endpoint deprecation. |
| https://help.splunk.com/en/splunk-cloud-platform/mcp-server-for-splunk-platform/1.2/oauth-for-mcp-server | MCP Server 1.2 OAuth prerequisites and Cloud-only enablement. |
| https://cloud.cisco.com/docs/en/cisco-cloud-control-getting-started/cisco-cloud-control-getting-started.html | Current Cisco Cloud Control Controlled Availability, supported product/capability matrix, identity/onboarding, and experience-layer boundary. |
| https://lantern.splunk.com/Splunk_and_Cisco_Use_Cases/Connecting_the_Splunk_platform_to_Cisco_Cloud_Control_and_AI_Canvas/Integrating_Splunk_Cloud_Platform_with_Cisco_Cloud_Control | Current Splunk–Cloud Control CA prerequisites: Splunk Cloud 10.5.2605.3, US commercial AWS, tenant approval, verified identity/domain, and terms. |
| https://lantern.splunk.com/Splunk_and_Cisco_Use_Cases/Connecting_the_Splunk_platform_to_Cisco_Cloud_Control_and_AI_Canvas/Integrating_Splunk_Cloud_Platform_with_AI_Canvas | AI Canvas with Splunk prerequisites and limits: Cloud Control enabled, latest AI Assistant and MCP Server, `mcp_tool_execute`, 100 rows per card, and forbidden-command failures. |
| https://blogs.cisco.com/ai/announcing-cisco-cloud-control-agent-builder | Cloud Control Studio Agent Builder announcement dated 2026-06-02 and its when-and-if-available boundary; no CA or GA lifecycle is inferred from the announcement. |
| https://www.cisco.com/c/en/us/td/docs/ai/cisco-cloud-control/release-notes/cisco-cloud-control-release-notes.html | Cisco Cloud Control release notes updated 2026-08-13. Shipped-feature tables for June, July, and August 2026 list no Cloud Control Studio or Agent Builder feature, the related-documentation set ships no Studio guide, and Cloud Control itself is still Controlled Availability for US-based infrastructure. Negative evidence keeping Cloud Control Studio Agent Builder at roadmap. Verified 2026-08-20. |
| https://www.cisco.com/site/us/en/products/security/security-analytics/security-analytics-logging/index.html | Cisco SAL product boundary; do not conflate it with Machine Data Lake. |

## Reconciled Timeline Notes

- The September 2025 release targeted a Hugging Face time-series model in
  November 2025. Cisco Time Series Model 1.0 is now published as an Apache-2.0
  open model, and the hosted Cisco Deep Time Series Model integration reached
  general availability in AI Toolkit 6.0.0. They remain separately governed
  layers: keep platform integration and future multivariate/covariate
  enhancements separate from open-model availability.
- The AI Toolkit baseline moved from 5.7.4 with PSC 4.3.2 to 6.0.2 with PSC
  4.3.4. The 6.0.2 version-dependency table pairs both 6.0.1 and 6.0.2 with
  4.3.4 only, so the previous 6.x-era pairing with 4.3.2 was unsupported as
  well as dated.
- Cloud Control Studio Agent Builder was re-derived on 2026-08-20 and stays at
  roadmap. The Cisco Cloud Control release notes updated 2026-08-13 are the
  authoritative current source and list no Studio or Agent Builder feature in
  the June, July, or August 2026 shipped-feature tables. Splunk AI Toolkit
  Agent Launchpad reaching GA is not evidence about this Cisco capability.
- The launch said additional federation sources would arrive in 2026. Current
  10.5 documentation now names Snowflake and DDSS in addition to Splunk, S3,
  Microsoft Azure, Azure Databricks, and Amazon Security Lake.
- Marketing calls the new Federated Search capabilities GA, but its own
  store-specific material and product docs retain activation or controlled-
  availability constraints. Record status per target.
- Machine Data Lake remains alpha in June 2026 public material. Do not infer
  GA from the older generic statement that the architecture uses available
  Splunk Enterprise and Cloud capabilities.
- The Cisco Live 2026 blog called Splunk Agent Builder alpha with a Fall 2026
  GA target. That target has passed and been met: AI Toolkit 6.0.0 shipped the
  capability as generally available Agent Launchpad, and the 5.6.4
  feature-preview page it was derived from now returns HTTP 404. Cite AI
  Toolkit 6.0.2 documentation for this lifecycle and treat region, egress-IP,
  LLM-connection, and enabled-agent requirements as reachability gates rather
  than as an earlier product stage.
