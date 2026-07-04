# Cisco Data Fabric Setup Reference

## Product Boundary

Cisco Data Fabric is a unifying architecture powered by Splunk Enterprise and
Splunk Cloud Platform capabilities. It connects data management, real-time
indexed analytics, external and federated data, catalog/context, and governed
AI activation. It is not a standalone package, appliance, API, license, data
lake, or replacement name for every Splunk product.

Public material mixes already available capabilities with activation-gated,
controlled-availability, alpha, preview, roadmap, and deprecated surfaces.
This skill records two independent fields for every capability:

- `product_stage`: current product or documentation stage.
- `repo_status`: what this repository can safely render, delegate, validate,
  or hand off.
- `access_requirement`: tenant activation, commercial entitlement, preview/CA
  enrollment, role, or other access gates, independent of product lifecycle.

A product marked GA can still be blocked for production by its owning child
skill after package inspection or environment validation.

## Rendered Artifacts

- `coverage-report.json` and `coverage-report.md`
- `product-matrix.json` and `product-matrix.md`
- `availability-matrix.md`
- `apply-plan.json`
- `metadata.json`
- `doctor-report.md`
- `gap-register.md`
- `gap-register.json` with the executor's blocking-error count
- `handoff.md`
- `architecture/layer-model.md`
- `data-management/pipeline-readiness.md`
- `federation/target-matrix.md`
- `storage-catalog/tiering-and-catalog-readiness.md`
- `ai/activation-readiness.md`
- `governance/trust-readiness.md`
- `experience/cross-domain-handoff.md`
- `scripts/execute-<section>.sh`

## Delegated Owner Map

| Surface | Primary owner |
| --- | --- |
| Cisco Data Fabric architecture and coverage | `cisco-data-fabric-setup` |
| Edge routing and customer-managed runtime | `splunk-edge-processor-setup` |
| Splunk Cloud ingest-time pipelines | `splunk-ingest-processor-setup` |
| Shared SPL2 templates and linting | `splunk-spl2-pipeline-kit` |
| Splunk-to-Splunk and external federation | `splunk-federated-search-setup` |
| Data Manager cloud-source onboarding and S3 Promote | `splunk-cloud-data-manager-setup` |
| Ingest Actions routing and RFS | `splunk-ingest-actions-setup` |
| DDAA archive lifecycle | `splunk-ddaa-archive-setup` |
| Enterprise SmartStore/index lifecycle | `splunk-index-lifecycle-smartstore-setup` |
| AI Toolkit, PSC, DSDL, hosted-model readiness | `splunk-ai-ml-toolkit-setup` |
| Splunk MCP Server | `splunk-mcp-server-setup` |
| Splunk AI Assistant | `splunk-ai-assistant-setup` |
| Data usability and downstream readiness | `splunk-data-source-readiness-doctor` |
| CIM/OCSF and data models | `splunk-cim-data-model-setup` |
| Knowledge objects and business metadata | `splunk-knowledge-objects-setup`, `splunk-itsi-config` |
| Agent behavior, quality, and cost telemetry | `splunk-observability-ai-agent-monitoring-setup` |
| Cisco Cloud Control and AI Canvas integration | `cisco-cloud-control-setup` |
| Cisco product source resolution | `cisco-product-setup` |

## Federation Rules

- Keep Federated Search for Splunk separate from cloud data-store
  connections. FSS2S supports Splunk Enterprise and Splunk Cloud combinations;
  Data Management external-store workflows are Splunk Cloud surfaces.
- In Splunk Cloud 10.5, enumerate Amazon S3, Microsoft Azure, Azure
  Databricks, Snowflake, DDSS, and Amazon Security Lake separately.
- Require SPL2, store-specific credentials, region/network prerequisites,
  role capabilities, catalog choices, and tenant activation where documented.
- Amazon S3 can use AWS Glue, an Apache Iceberg REST catalog, or a
  Splunk-native catalog. Delta Lake and Apache Iceberg can be table formats in
  supported catalog paths; they are not each generic writable destinations.
- The current Amazon S3 Data Management workflow can combine pipeline routing
  and federated search. Do not describe that as universal across every store.
- Track DSU usage only on surfaces whose documentation defines it. Do not
  infer one entitlement model for all federation targets.
- Treat the legacy `aws_s3` federated-provider/index model as deprecated on
  10.5. Existing objects are read-only and migrated to Data Management; new
  automation belongs to a stable public connection/dataset contract if one is
  published.

## Storage And Context Rules

- Use the Splunk index for low-latency, continuous correlation and alerts.
- Use external/federated storage for appropriate historical, exploratory,
  compliance, enrichment, or cost-control workloads.
- Keep Machine Data Lake at alpha and account-team handoff. Its stated model
  is a scalable, schema-less landing environment that can catalog, enrich, and
  govern telemetry before immediate indexing.
- Do not conflate Machine Data Lake with DDSS, DDAA, SmartStore, an arbitrary
  S3 bucket, or Cisco SAL.
- Treat Data Catalog, knowledge graph, business context, lineage, and policy
  as separate context/governance requirements. Public configuration depth is
  uneven, so the parent records owners and evidence rather than inventing CRUD.

## AI And Experience Rules

- AI Toolkit and its compatible PSC are the model-workflow foundation.
- Keep Cisco Deep Time Series Model at its current hosted beta/feature-preview
  boundary. Cisco Time Series Model 1.0 is separately available under Apache
  2.0 on Hugging Face; do not infer that its hosted integration is GA.
- Keep Splunk AI Toolkit Agent Builder at alpha with a public GA target of Fall
  2026, and Cloud Control Studio Agent Builder at announced/roadmap until Cisco
  establishes availability; target dates and the parent Cloud Control CA are
  not product-stage evidence for either builder.
- Splunk MCP Server product GA does not bypass the owning skill's package and
  production-safety findings. Use encrypted-token or documented OAuth flows,
  RBAC, tool controls, audit, and rate limits.
- Treat Cisco AI Canvas and Splunk/ITSI/Observability access in Cisco Cloud
  Control as experience-layer handoffs until the current integration is
  available for the tenant and a supported automation contract exists.
- During the current Controlled Availability, verify the documented Splunk
  Cloud `10.5.2605.3`, US commercial AWS, tenant-approval, identity/domain,
  terms, AI Assistant, MCP Server, and `mcp_tool_execute` prerequisites rather
  than generalizing the integration to every Splunk product or deployment.

## Coverage Statuses

Allowed `repo_status` values:

- `delegated_apply`
- `delegated_render`
- `render`
- `ui_handoff`
- `validation`
- `not_applicable`

Allowed `product_stage` values:

- `architecture`
- `ga`
- `available`
- `controlled_availability`
- `alpha`
- `feature_preview`
- `roadmap`
- `deprecated`
- `version_dependent`

Do not encode sales activation or premium-add-on access as a lifecycle stage.
For example, current evidence treats Amazon S3 Federated Search and Amazon
Security Lake Federated Analytics as GA while their `access_requirement`
still records activation, scan entitlement, and premium-add-on constraints.

## Compatibility Baseline

The current source audit targets Splunk Cloud Platform `10.5.2605`, AI Toolkit
`5.7.4`, PSC `4.3.2`, Ingest Monitoring `1.2`, and Splunk MCP Server `1.2.1`.
Self-managed configuration continues to use public Splunk Enterprise 10.4
contracts unless a child skill has newer verified evidence.
