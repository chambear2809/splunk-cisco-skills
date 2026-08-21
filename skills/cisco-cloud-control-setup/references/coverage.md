# Coverage

| Key | Status | Owner | Apply boundary |
| --- | --- | --- | --- |
| cloud_control_platform | `render` | `cisco-cloud-control-setup` | Render adoption plan only; no Cloud Control API writes. |
| official_feature_coverage | `render` | `cisco-cloud-control-setup` | Render official Getting Started and related-resource feature coverage. |
| official_product_timeline | `render` | `cisco-cloud-control-setup` | Render Cisco's current Inventory, Topology, and Notifications matrix plus separately classified adjacent handoffs. |
| workflows_api | `render` | `cisco-cloud-control-setup` | Render Cisco Workflows API/OAS readiness only; no API calls. |
| admin_console | `ui_handoff` | Cisco Cloud Control Admin Console | Onboarding, tenant, integration, SSO, audit, and support actions remain UI handoffs. |
| cloud_control_studio | `ui_handoff` | Cisco Cloud Control Studio | Agent Builder and App Builder actions remain UI handoffs. |
| ai_canvas | `ca_handoff` | Cisco AI Canvas | Board templates and readiness prompts only. |
| data_fabric | `delegated_render` | `cisco-data-fabric-setup` | Dedicated parent renders and validates full architecture coverage; constituent applies remain separately gated. |
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
- Cisco Data Fabric readiness is delegated to a claim-level source ledger and lifecycle matrix covering Data Inputs, processing, all current federation targets and catalogs, indexed/external/alpha storage, context, open CTSM versus the GA hosted CDTSM, Splunk AI Toolkit Agent Launchpad separately from Cloud Control Studio Agent Builder, MCP, Cloud Control, AI Canvas, governance, and cross-domain consumers.
- Release-note open issues.

## Official Product Checklist

Catalyst SD-WAN Manager, Collaboration Control Hub, Intersight, Meraki, Nexus
Dashboard, Nexus Hyperfabric, Secure Access, Secure Firewall, and ThousandEyes
are the current direct matrix rows. Catalyst Center, Security Cloud Control,
Splunk Cloud, and Cisco IQ remain represented as explicitly non-equivalent
onboarding, product-family, CA-integration, or unverified/roadmap handoffs.

Allowed coverage statuses are `delegated_apply`, `delegated_render`, `render`, `ui_handoff`,
`ca_handoff`, `validate`, and `not_applicable`.
