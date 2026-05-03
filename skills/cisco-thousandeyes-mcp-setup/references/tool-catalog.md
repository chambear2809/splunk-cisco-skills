# ThousandEyes MCP Server tool catalog

Source of truth: `docs.thousandeyes.com/product-documentation/integration-guides/thousandeyes-mcp-server`. The list below mirrors the official tool table at the time of authoring; treat the doc as canonical if it diverges.

The skill **does not** filter the toolset at the server side — the server exposes everything by default. Per-client gating (auto-allow, manual approval) is what the rendered configs control.

## Read-only group (auto-allow recommended)

### Core monitoring

| Tool | Purpose |
|------|---------|
| List Tests | View all configured tests (web apps, services, networks) |
| Get Test Details | Detailed information for a specific test |
| List Events | Network and application problems within a time range |
| Get Event Details | Deep dive into specific events with impacted targets |
| List Alerts | Triggered or cleared alerts |
| Get Alert Details | Comprehensive information about specific alerts |
| Search Outages | Network and application outages with filters |

### Advanced analysis

| Tool | Purpose |
|------|---------|
| Get Anomalies | Detect metric anomalies in test data over time |
| Get Metrics | Aggregated metrics for custom dashboards/reports |
| Get Service Map | Distributed tracing service map for HTTP server tests |

### AI-powered

| Tool | Purpose |
|------|---------|
| Views Explanations | Explain specific test results and visualizations |

### Endpoint monitoring

| Tool | Purpose |
|------|---------|
| List Endpoint Agents and Tests | List Endpoint Agents and/or tests with filtering |
| Get Endpoint Agent Metrics | Time series data from Endpoint Agents (network, web, wireless, cellular) |
| Get Connected Device | Full details for one Connected Device by agent_id |

### Agent management

| Tool | Purpose |
|------|---------|
| Get Cloud and Enterprise Agents | List Cloud and Enterprise Agents with filters |

### Network path analysis

| Tool | Purpose |
|------|---------|
| Get Path Visualization | Hop-by-hop network path |
| Get Full Path Visualization | Comprehensive path data for all agents and rounds |
| Get BGP Test Results | BGP reachability and routing information |
| Get BGP Route Details | AS path and routing information for prefixes |

### Account management

| Tool | Purpose |
|------|---------|
| Get Account Groups | List available account groups |

### Templates

| Tool | Purpose |
|------|---------|
| Search Templates | List/filter templates available in the account group |

## Write / Instant-Test group (requires `--accept-te-mcp-write-tools`)

### Test management

| Tool | Purpose | Risk |
|------|---------|------|
| Create Synthetic Test | Create a new scheduled synthetic test | Mutates TE configuration; ongoing units |
| Update Synthetic Test | Update an existing synthetic test | Mutates TE configuration |
| Delete Synthetic Test | Delete a scheduled synthetic test | Permanent loss of historical scheduling |

### Instant tests

| Tool | Purpose | Risk |
|------|---------|------|
| Run Instant Test | Run, rerun, and retrieve results for on-demand tests | **Consumes ThousandEyes units identically to scheduled tests.** Pricing is per single round. |

### Templates

| Tool | Purpose | Risk |
|------|---------|------|
| Deploy Template | Deploy a template to create tests, dashboards, alert rules | Provisions multiple assets at once; combines test, dashboard, and alert risk |

## Selective enablement guidance

The MCP docs warn: *"Enabling too many tools at once can lead to degraded MCP server performance, including delayed responses and timeouts."* Use the read-only group as the baseline; enable individual write tools only when a specific workflow needs them and the operator has reviewed the consumption / mutation risk.
