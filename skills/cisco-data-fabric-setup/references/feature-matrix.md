# Cisco Data Fabric Feature Matrix

Use this matrix to decide which child workflow owns implementation. Product
stage and repository actionability are deliberately separate.

## Architecture

| Surface | Product stage | Repository owner | Boundary |
| --- | --- | --- | --- |
| Cisco Data Fabric | Architecture | `cisco-data-fabric-setup` | Unifying architecture powered by Splunk, not one installable product. |
| Splunk Platform foundation | Available | Splunk platform skills | Existing Splunk Enterprise and Cloud capabilities form the baseline. |
| Cross-domain operations | Architecture | ES, ITSI, Observability, Cisco product skills | SecOps, ITOps, Engineering/DevOps, and NetOps are consumers/domains. |
| Edge, cloud, and on-premises | Architecture | Edge, Ingest, Enterprise, Cloud skills | Availability differs by component and deployment. |
| Open/modular integrations | Architecture | Owning integration skills | Do not infer a universal Cisco Data Fabric API. |

## Data Management

| Surface | Product stage | Repository owner | Boundary |
| --- | --- | --- | --- |
| Collection and onboarding | Available | TA, OTel, UF, Agent Management, Data Manager skills | Source-specific prerequisites still apply. |
| Edge Processor | Available | `splunk-edge-processor-setup` | Customer-managed edge runtime and destinations. |
| Ingest Processor | Available | `splunk-ingest-processor-setup` | Splunk Cloud Victoria Experience; no private CRUD claims. |
| SPL2 pipelines and searches | Version-dependent | `splunk-spl2-pipeline-kit` | Runtime profiles and supported commands differ. |
| Filtering, shaping, redaction, routing, tiering | Available | Edge/Ingest/SPL2 skills | Preview and validate before production routing. |
| Automated Field Extraction | Controlled availability | `splunk-ingest-processor-setup` | Region-gated UI assistance. |
| Guided Onboarding with Auto-Schematization | Alpha | `splunk-ingest-processor-setup` | UI/alpha handoff; review generated schemas. |
| Ingest Monitoring 1.2 | GA | `splunk-data-source-readiness-doctor` | Volume, event count, latency, no-ingestion, alerts, and investigation. |

## Federation And Catalogs

| Surface | Product stage | Access requirement | Repository owner | Boundary |
| --- | --- | --- | --- | --- |
| Federated Search for Splunk | Available | Deployment-combination, role, and network prerequisites | `splunk-federated-search-setup` | Standard/transparent mode and knowledge-object rules. |
| Amazon S3 | GA | Sales activation and scan entitlement | `splunk-federated-search-setup` | Data Management connections/datasets on AWS-hosted Cloud. |
| Microsoft Azure ADLS/Blob | Controlled availability | CA enrollment and sales activation | `splunk-federated-search-setup` | Store, region, allowlist, catalog, and tenant constraints. |
| Azure Databricks Unity Catalog | Controlled availability | CA enrollment and sales activation | `splunk-federated-search-setup` | Delta Sharing credentials and runtime prerequisites. |
| Snowflake tables/views | Available in current docs | Sales activation and scan entitlement | `splunk-federated-search-setup` | 10.5 AWS-hosted prerequisites and PAT handoff. |
| DDSS in Amazon S3 | Available in current docs | Sales activation and scan entitlement | `splunk-federated-search-setup` | No Azure/GCP DDSS federation; SQS catalog sync. |
| Amazon Security Lake | GA | Premium add-on, activation, and scan entitlement | `splunk-federated-search-setup` | Federated Analytics, OCSF, DSU, same-region, and topology constraints. |
| AWS Glue catalog | Available for supported S3 paths | Dataset/IAM/KMS access | `splunk-federated-search-setup` | Supports documented table formats and policies. |
| Apache Iceberg REST catalog | Available with restrictions | Reachable unauthenticated catalog path | `splunk-federated-search-setup` | Authorization-requiring REST catalogs are not currently supported. |
| Splunk-native catalog and crawler | Available for supported datasets | Dataset and role access | `splunk-federated-search-setup` | Inferred or manual schema/partitions; sync requirements apply. |
| Legacy `aws_s3` provider/index path | Deprecated on 10.5 | Existing reviewed tenant only | `splunk-federated-search-setup` | Do not create new providers; verify migrated Data Management datasets. |

## Storage, Context, And Governance

| Surface | Product stage | Repository owner | Boundary |
| --- | --- | --- | --- |
| Splunk index | GA | Platform/index skills | Real-time execution, correlation, alerting, and hot search. |
| Machine Data Lake | Alpha | `cisco-data-fabric-setup` handoff | No public provisioning API; confirm program and tenant access. |
| Global Splunk Catalog discovery UI | Version-dependent gradual 10.5 rollout | `cisco-data-fabric-setup` handoff | Discover indexed and supported federated datasets; distinguish from dataset catalogs. |
| Machine Data Lake cataloging/enrichment | Alpha/readiness | `cisco-data-fabric-setup` handoff | MDL context is documented; CRUD and general lineage are not claimed. |
| S3 Promote | Available where Data Manager supports it | `splunk-cloud-data-manager-setup` | Historical S3 ingestion, distinct from federation and MDL. |
| DDSS/DDAA | Version-dependent | Federated Search, ACS, DDAA skills | Distinct self-storage/archive products and workflows. |
| SmartStore | Available for supported Enterprise topologies | `splunk-index-lifecycle-smartstore-setup` | Not Machine Data Lake. |
| Knowledge graph and business context | Architecture/roadmap | ITSI, CIM, knowledge-object skills | Public CDF CRUD contract is not assumed. |
| RBAC, audit, lineage, policy, human approval | Required governance | Admin/readiness/Cloud Control skills | Evidence gate for production agent access and action. |

## AI Activation And Experience

| Surface | Product stage | Repository owner | Boundary |
| --- | --- | --- | --- |
| Splunk AI Toolkit 5.7.4 | GA | `splunk-ai-ml-toolkit-setup` | Requires compatible PSC and search-tier placement. |
| DSDL/external model runtimes | Available plus handoffs | `splunk-ai-ml-toolkit-setup` | Runtime, TLS, image, network, GPU, and governance ownership remains explicit. |
| Hosted foundation models | Version/tenant dependent | `splunk-ai-ml-toolkit-setup` | Foundation-Sec, CDTSM, and GPT-OSS availability must be confirmed. |
| Cisco Deep Time Series Model | Feature preview / hosted beta | `splunk-ai-ml-toolkit-setup` | Forecasting/anomaly workflows; do not call it GA. |
| Cisco Time Series Model 1.0 | Available open model | `cisco-data-fabric-setup` | Apache-2.0 model and self-hosting path; separate from hosted CDTSM preview. |
| Splunk AI Toolkit Agent Builder | Alpha; GA target Fall 2026 | `splunk-ai-ml-toolkit-setup` | No-code agents with tools/knowledge; roadmap until released. |
| Agent Builder knowledge-base and MCP connections | Alpha/private preview | `splunk-ai-ml-toolkit-setup` | Requires preview enrollment, `edit_agent_connections`, approved sources, and secret-safe UI handling. |
| `aiagent` invocation and run history | Alpha/private preview | `splunk-ai-ml-toolkit-setup` | Validate `run_agents`, invocation limits/timeouts, and `ai_agent_run_history_index` governance; no private API or index creation is claimed. |
| Cloud Control Studio Agent Builder | Announced / roadmap | `cisco-cloud-control-setup` | Cisco uses future-tense and when-and-if-available language. Do not infer CA from Cloud Control's own lifecycle or conflate it with Splunk AI Toolkit Agent Builder. |
| Splunk MCP Server | GA product; repo child safety gate | `splunk-mcp-server-setup` | Product GA does not override child package findings. |
| Splunk AI Assistant tools through MCP | Version-dependent | MCP and AI Assistant skills | AI Assistant must be installed; RBAC/tool controls apply. |
| Cisco AI Canvas + Splunk | Controlled availability | `cisco-cloud-control-setup` | Eligible US commercial AWS Splunk Cloud 10.5.2605.3 during CA; tenant approval, identity/domain, terms, current AI Assistant/MCP, and `mcp_tool_execute` are prerequisites. |
| AI Canvas Splunk execution limits | Controlled availability | `cisco-cloud-control-setup` | Results are capped at 100 rows per card; some SPL commands are forbidden and fail when a card is refreshed or run. |
| Agent Observability | Available/tenant dependent | `splunk-observability-ai-agent-monitoring-setup` | Monitor quality, behavior, latency, cost, and guardrails. |

## Named External/Cisco Integrations

- Cisco product telemetry is resolved through `cisco-product-setup` and the
  first-class Cisco ingestion/Observability skills.
- Cisco Security Analytics and Logging (SAL) is a separate Cisco logging and
  analytics product. The 2025 Data Fabric announcement named it as an
  integration direction; this repo does not infer a public Data Fabric
  federation contract for SAL.
- Snowflake, Delta Lake, Apache Iceberg, Amazon S3, Microsoft Azure, Azure
  Databricks, DDSS, and Amazon Security Lake must retain their documented
  store/catalog/product semantics.
