# Cisco Cloud Control Setup Reference

Cisco Cloud Control is treated here as an AgenticOps adoption workflow, not as
a Splunkbase app installer and not as Cisco Security Cloud Control / CDO.

## Boundaries

- No direct Cisco Cloud Control mutation is implemented in this repo.
- Cloud Control Studio and AI Canvas are UI/CA handoffs until stable public
  developer contracts are available.
- Cisco Workflows API is a documented readiness surface. This skill renders
  the base URL, OAS, target/account-key, auth, and rate-limit checklist, but it
  does not make API calls.
- Executable work is limited to delegated child skills with existing supported
  render/apply surfaces.
- This parent skill never accepts or renders secret values.

## Rendered Artifacts

- `coverage-report.json` and `coverage-report.md`
- `apply-plan.json`
- `doctor-report.md`
- `handoff.md`
- `metadata.json`
- `platform/feature-coverage.md`
- `platform/product-integration-matrix.md`
- `platform/admin-readiness.md`
- `api/cloud-control-api-boundary.md`
- `api/workflows-api-readiness.md`
- `studio/agent-blueprints/*.md`
- `studio/mcp-connector-plan.md`
- `studio/app-builder-briefs/*.md`
- `ai-canvas/board-templates/*.md`
- `data-fabric/cisco-data-fabric-2026-readiness.md`

## Official Cisco Cloud Control Surfaces

The skill renders coverage for all currently linked Getting Started related
resources: Release Notes, Getting Started, AI Canvas, Inventory, Licensing,
RBAC, Topology, Workflows, and Cisco Multicloud Fabric.

Feature coverage includes onboarding, tenant groups, product integrations, AI
context management, users and roles, SSO, audit logs, AI Assistant, AI Canvas,
Actions, Notifications, Favorites, Help/support workflows, inventory search,
licensing visibility, RBAC, topology scopes and health, workflows/atomics, API
readiness, targets/account keys, and Multicloud Fabric beta handoff. The
Splunk-specific AI Canvas path additionally records the exact `10.5.2605.3`,
current AI Assistant/MCP, `mcp_tool_execute`, 100-row-per-card, visualization,
and forbidden-command constraints.

The current capability matrix is kept separate from adjacent handoffs. Its
rows are Catalyst SD-WAN Manager, Collaboration Control Hub, Intersight,
Meraki, Nexus Dashboard, Nexus Hyperfabric, Secure Access, Secure Firewall,
and ThousandEyes, with independent Inventory, Topology, and Notifications
columns. Catalyst Center onboarding context, Security Cloud Control family
routing, the Splunk Cloud CA integration, and Cisco IQ are rendered as
separately classified handoffs rather than being promoted to matrix rows.

## Delegated Owners

| Area | Owner |
| --- | --- |
| Cisco Workflows API readiness | Rendered API/OAS handoff; no direct API calls |
| Cisco Data Fabric | `cisco-data-fabric-setup`; complete architecture router, lifecycle matrix, source ledger, gap doctor, and validated child-render handoffs |
| Data management | Dedicated parent distinguishes Data Inputs, Edge Processor, Ingest Processor, SPL2, Automated Field Extraction CA, Guided Onboarding/Auto-Schematization alpha, and Ingest Monitoring |
| Machine Data Lake alpha | Dedicated parent readiness handoff; no provisioning API calls |
| Catalogs | Dedicated parent distinguishes global Splunk Catalog, dataset-native catalog, AWS Glue, Iceberg REST, Databricks Unity Catalog, and Machine Data Lake cataloging; no undocumented CRUD |
| Federation | Dedicated parent covers Splunk, Amazon S3, Microsoft Azure, Azure Databricks, Snowflake, DDSS, and Amazon Security Lake independently, plus legacy FSS3 migration and Cisco SAL boundaries |
| AI activation | Dedicated parent distinguishes AI Toolkit `6.0.2` with PSC `4.3.4`, open CTSM, GA hosted CDTSM, GA Splunk AI Toolkit Agent Launchpad, the separate announced/roadmap Cloud Control Studio Agent Builder, MCP, and AI Canvas CA |
| MCP | `splunk-mcp-server-setup` when `mcp.splunk_mcp_url` is set; `cisco-thousandeyes-mcp-setup` can render without Splunk credentials |
| AI agent monitoring | `splunk-observability-ai-agent-monitoring-setup` |
| Observability dashboards | `splunk-observability-dashboard-builder` |
| Observability detectors | `splunk-observability-native-ops` |
| Domain readiness | Product setup skills and product-router handoffs for Intersight, Nexus, Nexus Hyperfabric, ThousandEyes, Meraki, Catalyst, Catalyst SD-WAN, Security Cloud Control, Secure Access, Duo, ISE, Secure Firewall, Splunk Cloud, Collaboration Control Hub, and Cisco IQ |

See `references/research-ledger.md` and `references/coverage.md` for source
links and API-vs-handoff coverage.
