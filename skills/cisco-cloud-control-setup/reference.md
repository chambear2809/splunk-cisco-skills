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

## Official Cisco Cloud Control Surfaces

The skill renders coverage for all currently linked Getting Started related
resources: Release Notes, Getting Started, AI Canvas, Inventory, Licensing,
RBAC, Topology, Workflows, and Cisco Multicloud Fabric.

Feature coverage includes onboarding, tenant groups, product integrations, AI
context management, users and roles, SSO, audit logs, AI Assistant, AI Canvas,
Actions, Notifications, Favorites, Help/support workflows, inventory search,
licensing visibility, RBAC, topology scopes and health, workflows/atomics, API
readiness, targets/account keys, and Multicloud Fabric beta handoff.

Product coverage follows Cisco's current integration matrix: Meraki, Catalyst
Center, Nexus Dashboard, Nexus Hyperfabric, Intersight, Catalyst SD-WAN
Manager, Security Cloud Control, ThousandEyes, Splunk Cloud, Collaboration
Control Hub, and Cisco IQ.

## Delegated Owners

| Area | Owner |
| --- | --- |
| Cisco Workflows API readiness | Rendered API/OAS handoff; no direct API calls |
| Cisco Data Fabric | `splunk-federated-search-setup`, `splunk-edge-processor-setup`, `splunk-ingest-processor-setup`, `splunk-ai-ml-toolkit-setup`, `splunk-mcp-server-setup` |
| MCP | `splunk-mcp-server-setup` when `mcp.splunk_mcp_url` is set; `cisco-thousandeyes-mcp-setup` can render without Splunk credentials |
| AI agent monitoring | `splunk-observability-ai-agent-monitoring-setup` |
| Observability dashboards | `splunk-observability-dashboard-builder` |
| Observability detectors | `splunk-observability-native-ops` |
| Domain readiness | Product setup skills and product-router handoffs for Intersight, Nexus, Nexus Hyperfabric, ThousandEyes, Meraki, Catalyst, Catalyst SD-WAN, Security Cloud Control, Secure Access, Duo, ISE, Secure Firewall, Splunk Cloud, Collaboration Control Hub, and Cisco IQ |

See `references/research-ledger.md` and `references/coverage.md` for source
links and API-vs-handoff coverage.
