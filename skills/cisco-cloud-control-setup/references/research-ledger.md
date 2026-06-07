# Research Ledger

| Source | Use in this skill |
| --- | --- |
| https://cloud.cisco.com/docs/en/cisco-cloud-control-getting-started/cisco-cloud-control-getting-started.html | Official Getting Started workflow, product integration timeline, onboarding, AI context, integrations, users, tenants, SSO, audit logs, AI tools, Actions, Notifications, Favorites, Help, and related-resource index. |
| https://cloud.cisco.com/docs/en/cisco-cloud-control-rn-open-bugs/cisco-cloud-control-release-notes.html | Open issue review before production agent use. |
| https://cloud.cisco.com/docs/en/cisco-cloud-control-canvas/cisco-cloud-control-canvas.html | Official AI Canvas and AI Assistant use cases, prompt library, collaboration, knowledge, multimodal input, supported integration prompts, and limitations. |
| https://cloud.cisco.com/docs/en/cisco-cloud-control-inventory/cisco-cloud-control-inventory.html | Global inventory, AI-powered search, product-specific inventory support, and export/readiness limitations. |
| https://cloud.cisco.com/docs/en/cisco-cloud-control-licensing/cisco-cloud-control-licensing.html | Licensing visibility, supported licensing products/models, data availability, and report readiness. |
| https://cloud.cisco.com/docs/en/cisco-cloud-control-rbac/cisco-cloud-control-rbac.html | Role-based access control, supported roles, product-specific access, and user/role management. |
| https://cloud.cisco.com/docs/en/cisco-cloud-control-topology/cisco-cloud-control-topology.html | Topology, scopes, health, site/device drill-downs, and inventory/product navigation relationships. |
| https://cloud.cisco.com/docs/en/cisco-cloud-control-workflows/cisco-cloud-control-workflows.html | Workflows, atomics, Exchange, run monitoring, approvals, prompts, targets, variables, automation rules, webhooks, limits, and API run-rate constraints. |
| https://documentation.meraki.com/Platform_Management/Workflows/Workflows/Using_the_Workflows_API | Public Cisco Workflows API readiness basis, including REST path pattern, bearer auth, base URL, OAS download, and CORS caveat. |
| https://documentation.meraki.com/Platform_Management/Workflows/Targets/Targets_Account_Keys | Workflow target and account-key secret-handling model. |
| https://cloud.cisco.com/docs/en/cisco-multicloud-fabric/cisco-multicloud-fabric.html | Cisco Multicloud Fabric beta handoff, supported AWS/Azure/GCP/hybrid environments, and onboarding scope. |
| https://www.cisco.com/site/us/en/solutions/artificial-intelligence/agentic-ops/cisco-cloud-control/index.html | Cisco Cloud Control platform positioning and AgenticOps scope. |
| https://www.cisco.com/site/us/en/solutions/artificial-intelligence/agentic-ops/cloud-control-studio/index.html | Cloud Control Studio product boundary, native integrations, open MCP/API support, and AI Canvas deployment handoff. |
| https://newsroom.cisco.com/c/r/newsroom/en/us/a/y2026/m06/cisco-unveils-agentic-platform-for-operating-and-defending-critical-it-infrastructure.html | Launch context and distinction from legacy product-specific control surfaces. |
| https://blogs.cisco.com/ai/announcing-cisco-cloud-control-agent-builder | Cloud Control Studio Agent Builder handoff coverage. |
| https://blogs.cisco.com/ai/from-an-idea-to-a-live-app-on-cisco-in-minutes | Cloud Control Studio App Builder handoff coverage. |
| https://blogs.cisco.com/ai/ai-agents-need-built-in-security-here-is-how-cisco-does-it | AI Defense and governed agent execution readiness. |
| https://www.splunk.com/en_us/blog/leadership/splunk-cisco-live-agentic-operations.html | Splunk Platform, ITSI, Observability Cloud, and Cisco Data Fabric routing basis. |

## API Basis

The API basis is Cisco Workflows / Meraki Automation API readiness, not direct
Cisco Cloud Control platform mutation. The renderer writes
`api/workflows-api-readiness.md` with the public REST path pattern, bearer
authentication model, OAS requirement, target/account-key model, and published
run-rate limits. Direct Cisco Cloud Control Admin Console, Cloud Control Studio,
and AI Canvas writes remain operator handoffs.

## Product Boundary

Cisco Cloud Control is distinct from Cisco Security Cloud Control, formerly
Cisco Defense Orchestrator. The product router therefore exposes
`cisco_cloud_control` as a synthetic workflow handoff while keeping
`cisco_security_cloud_control` as the Security Cloud Control roadmap item.
