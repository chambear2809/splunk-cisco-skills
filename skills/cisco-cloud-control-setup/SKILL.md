---
name: cisco-cloud-control-setup
description: >-
  Render, validate, doctor, and optionally execute delegated setup plans for
  Cisco Cloud Control adoption, AI Canvas readiness, Cloud Control Studio
  handoffs, official Cloud Control feature coverage, Cisco Workflows API
  readiness, Cisco Data Fabric prerequisites, MCP connectors, Splunk AI Agent
  Monitoring, Observability content, and Cisco domain readiness. Use when the
  user asks to prepare Cisco Cloud Control, AgenticOps, AI Canvas, Cloud
  Control Studio, Cloud Control Workflows, or governed Cisco/Splunk agent
  execution workflows.
---

# Cisco Cloud Control Setup

This skill is a render-first parent workflow for Cisco Cloud Control adoption.
It does not call undocumented Cisco Cloud Control APIs. It renders the
operator plan, official feature/product coverage, Cisco Workflows API
readiness, Cloud Control Studio briefs, AI Canvas board templates, and
executable child-skill handoffs where supported.

## Supported Paths

1. **Cisco Data Fabric prerequisites**: delegate render/apply planning to
   Splunk Federated Search, Edge Processor, Ingest Processor, SPL2 Pipeline
   Kit, AI/ML Toolkit, and MCP Server skills. Render readiness for Machine
   Data Lake alpha, built-in Data Catalog, AI-powered data management, and
   expanded Data Management app federation without claiming unsupported
   product API writes.
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

Executable sections:

- `data-fabric`
- `mcp`
- `agent-observability`
- `observability-content`
- `domain-readiness`
- `cloud-control-studio`
- `ai-canvas`

`cloud-control-studio` and `ai-canvas` never mutate Cisco Cloud Control. They
only render or echo operator handoff artifacts.

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
