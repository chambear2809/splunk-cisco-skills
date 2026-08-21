---
name: cisco-cloud-control-setup
description: "Use when the user asks to prepare Cisco Cloud Control, AgenticOps, AI Canvas, Cloud Control Studio,
  Cloud Control Workflows, or governed Cisco/Splunk agent execution workflows. Render, validate, doctor,
  and optionally execute delegated setup plans for Cisco Cloud Control adoption, AI Canvas readiness,
  Cloud Control Studio handoffs, official Cloud Control feature coverage, Cisco Workflows API readiness,
  delegated Cisco Data Fabric architecture coverage, MCP connectors, Splunk AI Agent Monitoring,
  Observability content, and Cisco domain readiness."
compatibility: "Splunk Cloud Platform 10.5.2605: conditional. Follow documented package, entitlement, topology, and customer-managed runtime guardrails; self-managed paths remain on the public 10.4 baseline."
metadata:
  splunk_cloud_10_5: "conditional"
  compatibility_verified: "2026-08-20"
---

# Cisco Cloud Control Setup

## Prerequisites

| Tool or access | Purpose | Verify |
|---|---|---|
| Bash and Python 3 | Run bundled setup and validation helpers | `bash --version && python3 --version` |
| Required product/platform access | Inspect or configure the selected target | Complete the documented preflight |
| Credential files for live modes | Keep secrets out of chat | Verify paths only |

## Workflow Overview

```text
┌───────────┐   ┌───────────────┐   ┌───────────────┐   ┌─────────────────┐
│ Preflight │ → │ Render/review │ → │ Apply/handoff │ → │ Validate evidence │
└───────────┘   └───────────────┘   └───────────────┘   └─────────────────┘
```

## When to Activate

- Prepare Cisco Cloud Control, AgenticOps, AI Canvas, Cloud Control Studio, Cloud Control Workflows, or governed
  Cisco/Splunk agent execution workflows.
- Preview and review the cisco cloud control setup workflow before any live apply phase.
- Diagnose failed prerequisites, generated assets, configuration, or validation evidence.

## Scope

Follow the documented read-only or render-first path whenever it is available.
This skill does not imply permission to mutate live systems. Require explicit
apply flags, protected credentials, and operator review for state changes.

## Examples

Inspect the supported setup modes before selecting one:

```bash
bash skills/cisco-cloud-control-setup/scripts/setup.sh --help
```

Expected output: usage, supported modes, and required arguments are displayed
without changing the target environment.

Inspect validation modes before running completion checks:

```bash
bash skills/cisco-cloud-control-setup/scripts/validate.sh --help
```

Expected output: offline, live, and completion options are displayed when the
skill supports them; help exits without mutation.

## Troubleshooting

| Issue | Cause | Resolution |
|---|---|---|
| Preflight fails | A required tool or access path is missing | Resolve it before rendering or applying |
| Rendered assets are incomplete | Required non-secret inputs are absent | Complete intake and render again |
| Apply is blocked | Review, credentials, or explicit acceptance is missing | Use the documented handoff |
| Validation is incomplete | Live evidence is unavailable | Record the gap and keep completion open |

This skill is a render-first parent workflow for Cisco Cloud Control adoption.
It does not call undocumented Cisco Cloud Control APIs. It renders the
operator plan, official feature/product coverage, Cisco Workflows API
readiness, Cloud Control Studio briefs, AI Canvas board templates, and
executable child-skill handoffs where supported.

## Supported Paths

1. **Cisco Data Fabric architecture**: delegate the complete lifecycle-aware
   product, feature, federation, storage/catalog, context, AI, governance, and
   source-evidence packet to `cisco-data-fabric-setup`. That dedicated parent
   routes constituent Splunk skills only when it has reviewed non-secret
   inputs and never claims a standalone Cisco Data Fabric package or API.
2. **MCP connectors**: delegate Splunk MCP Server and ThousandEyes MCP client
   setup plans. Splunk MCP client rendering is emitted only when
   `mcp.splunk_mcp_url` is set, because the child skill otherwise needs
   Splunk credentials to derive the endpoint. ThousandEyes MCP can render
   independently.
3. **Agent observability**: delegate Splunk AI Agent Monitoring setup.
4. **Observability content**: delegate dashboards and detectors to existing
   Observability skills.
5. **Official Cloud Control surfaces**: render coverage for onboarding,
   tenant groups, product integrations, AI context, users/roles, SSO, audit
   logs, AI Assistant, AI Canvas, Actions, Notifications, Favorites, Inventory,
   Licensing, RBAC, Topology, Workflows, release notes, and Multicloud Fabric.
6. **Cisco Workflows API readiness**: render the documented API/OAS, target,
   account-key, auth, and rate-limit checklist without making API calls.
7. **Domain readiness**: render child-skill handoffs for Intersight, Nexus,
   Nexus Hyperfabric, ThousandEyes, Meraki, Catalyst Center, Catalyst SD-WAN,
   Security Cloud Control, Secure Access, Duo, ISE, Secure Firewall, Splunk
   Cloud, Collaboration Control Hub, and Cisco IQ.
8. **Cloud Control Studio and AI Canvas**: render UI/CA handoff artifacts only.

## Safe First Command

```bash
bash skills/cisco-cloud-control-setup/scripts/setup.sh --help
```

## Primary Workflow

Render from the example intake:

```bash
bash skills/cisco-cloud-control-setup/scripts/setup.sh \
  --render \
  --validate \
  --spec skills/cisco-cloud-control-setup/template.example \
  --output-dir cisco-cloud-control-rendered
```

Run the doctor report:

```bash
bash skills/cisco-cloud-control-setup/scripts/setup.sh \
  --doctor \
  --spec skills/cisco-cloud-control-setup/template.example \
  --output-dir cisco-cloud-control-rendered
```

Review delegated execution without changing anything:

```bash
bash skills/cisco-cloud-control-setup/scripts/setup.sh \
  --execute data-fabric,mcp,agent-observability \
  --dry-run \
  --json \
  --spec skills/cisco-cloud-control-setup/template.example
```

Execute only reviewed delegated sections:

```bash
bash skills/cisco-cloud-control-setup/scripts/setup.sh \
  --execute data-fabric,mcp \
  --accept-execute \
  --spec skills/cisco-cloud-control-setup/template.example \
  --output-dir cisco-cloud-control-rendered
```

## CLI Contract

`setup.sh` supports `--render`, `--validate`, `--doctor`,
`--execute SECTION[,SECTION]`, `--accept-execute`, `--dry-run`, `--json`,
`--spec PATH`, and `--output-dir DIR`.

Delegated executable sections:

- `data-fabric`
- `mcp`
- `agent-observability`
- `observability-content`
- `domain-readiness` (handoff-only; an execute request exits nonzero)
- `cloud-control-studio` (handoff-only; an execute request exits nonzero)
- `ai-canvas` (handoff-only; an execute request exits nonzero)

The `data-fabric` section runs only the dedicated parent's render and static
validation workflow. Any constituent apply remains behind the owning child
skill's explicit approval gates.

`domain-readiness`, `cloud-control-studio`, and `ai-canvas` never mutate Cisco
Cloud Control. They render operator handoff artifacts, and an explicit execute
request exits nonzero so a handoff cannot be mistaken for an applied change.

The Cisco Workflows API is treated as a readiness surface: this skill renders
the public API/OAS, target, account-key, and rate-limit checklist, but it does
not issue Workflows API calls or claim a direct Cisco Cloud Control platform
mutation API.

## Secret Handling

This parent skill rejects direct secret flags such as `--token`, `--password`,
`--api-key`, `--client-secret`, and `--private-key`. Specs must not contain raw
secret-looking keys such as `token`, `password`, `api_key`, `client_secret`, or
`private_key`. Put credentials in the delegated child skill's supported secret
files and keep those values out of chat and argv.

## Validation

```bash
bash skills/cisco-cloud-control-setup/scripts/validate.sh \
  --output-dir cisco-cloud-control-rendered
```

For code validation:

```bash
python3 -m py_compile \
  skills/cisco-cloud-control-setup/scripts/render_assets.py
```

See `reference.md` for the source ledger, coverage boundaries, and delegated
skill map.
