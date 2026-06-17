# Coverage

| Key | Status | Owner | Apply boundary |
| --- | --- | --- | --- |
| cloud_control_platform | `render` | `cisco-cloud-control-setup` | Render adoption plan only; no Cloud Control API writes. |
| official_feature_coverage | `render` | `cisco-cloud-control-setup` | Render official Getting Started and related-resource feature coverage. |
| official_product_timeline | `render` | `cisco-cloud-control-setup` | Render Cisco's navigation, inventory, and AI Canvas product matrix. |
| workflows_api | `render` | `cisco-cloud-control-setup` | Render Cisco Workflows API/OAS readiness only; no API calls. |
| admin_console | `ui_handoff` | Cisco Cloud Control Admin Console | Onboarding, tenant, integration, SSO, audit, and support actions remain UI handoffs. |
| cloud_control_studio | `ui_handoff` | Cisco Cloud Control Studio | Agent Builder and App Builder actions remain UI handoffs. |
| ai_canvas | `ca_handoff` | Cisco AI Canvas | Board templates and readiness prompts only. |
| data_fabric | `delegated_apply` | Splunk Data Fabric child skills | Child skills own render/apply/validate; Machine Data Lake/Data Catalog remain readiness handoffs. |
| mcp | `delegated_apply` | Splunk MCP and ThousandEyes MCP child skills | Child skills own client writes and token-file handling. |
| agent_observability | `delegated_apply` | `splunk-observability-ai-agent-monitoring-setup` | Child skill owns collector/runtime/dashboard/detector apply. |
| observability_content | `delegated_apply` | Observability dashboard/native ops skills | Child skills own API writes when explicitly applied. |
| domain_readiness | `render` | Cisco product setup skills | Parent renders handoff artifacts only. |

## Official Feature Checklist

- Onboarding, tenant linking, tenant groups, tenant switcher, and product association.
- AI context for Meraki and ThousandEyes.
- Meraki, ThousandEyes, and Collaboration Control Hub Admin Console integrations.
- Users, roles, Nexus Dashboard access, SSO, service-provider certificates, and audit logs.
- AI Assistant, AI Canvas, Actions, Notifications, Favorites, and Help/support workflows.
- Inventory, licensing, RBAC, topology, workflows/atomics, targets/account keys, webhooks, and Multicloud Fabric beta.
- Cisco Data Fabric 2026 readiness: Machine Data Lake alpha, built-in Data Catalog, AI-powered data management, expanded federated search, SPL2 pipeline templates, AI Toolkit/CDTSM, and MCP access.
- Release-note open issues.

## Official Product Checklist

Meraki, Catalyst Center, Nexus Dashboard, Nexus Hyperfabric, Intersight,
Catalyst SD-WAN Manager, Security Cloud Control, ThousandEyes, Splunk Cloud,
Collaboration Control Hub, and Cisco IQ are represented in rendered coverage.

Allowed coverage statuses are `delegated_apply`, `render`, `ui_handoff`,
`ca_handoff`, `validate`, and `not_applicable`.
