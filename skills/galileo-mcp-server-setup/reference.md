# Galileo MCP Server Setup Reference

## Source Guidance

- Galileo MCP Server docs:
  `https://docs.galileo.ai/getting-started/mcp/setup-galileo-mcp`
- Galileo docs coverage index:
  `https://docs.galileo.ai/llms-full.txt`
- Splunk Agent Observability docs coverage index:
  `https://agent-observability-docs.splunk.com/llms-full.txt`
- MCP tool-call logging:
  `https://docs.galileo.ai/how-to-guides/basics/log-mcp-server-calls/log-mcp-server-calls`
- MCP Streamable HTTP transport:
  `https://modelcontextprotocol.io/specification/2025-03-26/basic/transports`
- Galileo Logger:
  `https://docs.galileo.ai/sdk-api/logging/galileo-logger`
- Integrations overview:
  `https://docs.galileo.ai/sdk-api/third-party-integrations/overview`
- Agentic metrics:
  `https://docs.galileo.ai/concepts/metrics/agentic/agentic-overview`
- SDK example:
  `https://github.com/rungalileo/sdk-examples/tree/main/python/logging-samples/log-mcp-calls`
- July 7, 2026 release notes:
  `https://docs.galileo.ai/release-notes#2026-07-07`
- July 21, 2026 release notes:
  `https://docs.galileo.ai/release-notes#2026-07-21`
- August 4, 2026 release notes:
  `https://docs.galileo.ai/release-notes#2026-08-04`
- August 7, 2026 naming and documentation boundary:
  `https://docs.galileo.ai/release-notes#2026-08-07`
- Post-August 7 onboarding documentation:
  `https://agent-observability-docs.splunk.com`
- AI Assistant beta:
  `https://docs.galileo.ai/concepts/ai-assistant`
- Generic alert webhooks:
  `https://docs.galileo.ai/how-to-guides/basics/set-up-alerts-on-logs`
- Experiment groups:
  `https://docs.galileo.ai/sdk-api/experiments/experiment-groups`
- Scoped Trends API:
  `https://docs.galileo.ai/api-reference/trends_dashboard/get-trends`

## Rendered Layout

By default, assets are written under `galileo-mcp-rendered/`:

- `mcp/cursor.mcp.json`
- `mcp/vscode.mcp.json`
- `mcp/claude.mcp.json`
- `mcp/kiro.mcp.json`
- `mcp/codex-register-galileo-mcp.sh`
- `mcp/run-galileo-mcp.js`
- `mcp/run-galileo-mcp.sh`
- `mcp/.env.galileo-mcp.example`
- `mcp/README.md`
- `coverage/product-gap-matrix.json`
- `coverage/tool-catalog.json`
- `observability/mcp-tool-span-logging.md`
- `metadata.json`

## Endpoint Rules

Default Galileo Cloud MCP URL:

```text
https://api.galileo.ai/mcp/http/mcp
```

Non-loopback endpoints must use HTTPS. HTTP is accepted only for local
validation on `localhost`, `*.localhost`, `127.0.0.0/8`, or `::1`-class
loopback addresses. This applies consistently to renderer output and live
probes so direct Cursor/VS Code configurations cannot carry an API key over a
cleartext remote connection.

The hosted `app.galileo.ai` URL maps to `api.galileo.ai`. For self-hosted
Galileo, derive the URL by replacing the first `console` label with `api` and
appending `/mcp/http/mcp`. Examples:

- `https://app.galileo.ai` ->
  `https://api.galileo.ai/mcp/http/mcp`

- `https://console.galileo.example.com` ->
  `https://api.galileo.example.com/mcp/http/mcp`
- `https://console-galileo.apps.mycompany.com` ->
  `https://api-galileo.apps.mycompany.com/mcp/http/mcp`

## Setup Modes

- `--render`: render client configuration and handoff files.
- `--validate`: run static validation against rendered files.
- `--probe`: run a live no-secret MCP metadata probe.
- `--doctor`: render, validate, and probe.
- `--apply`: render and register Codex with a file-backed key. Other client
  config merges remain manual and fail closed.
- `--dry-run`: print the render plan without writing files.
- `--json`: emit JSON for dry-run and probe summaries.
- `--spec`: read the non-secret YAML/JSON intake file; command-line flags
  override spec values.

Apply changes Codex MCP registration only; no mode writes Cursor, VS Code,
Claude, or Kiro config paths.

## Local stdio bridge

Codex, Claude Code, and Kiro use the rendered dependency-free Node.js bridge.
It translates newline-delimited stdio JSON-RPC into MCP Streamable HTTP POSTs,
handles JSON and SSE responses, carries `Mcp-Session-Id` and the negotiated
`MCP-Protocol-Version`, opens the optional server SSE notification stream, and
closes stateful sessions with DELETE. All JSON-RPC methods are transported,
including initialize, initialized notifications, tools/list, tools/call,
prompts, and resources.

The bridge orders initialize and `notifications/initialized`, then permits
concurrent POSTs. This is required for `notifications/cancelled` to reach the
server while its target tool call is still running. Server SSE frames are
bounded per event rather than across the stream lifetime. Closed or transiently
failed streams reconnect with capped exponential backoff; explicit unsupported,
authorization, or redirect responses disable optional GET streaming while
normal POST methods remain available.

The bridge deliberately does not use `mcp-remote`. It rejects 3xx responses
instead of following them, never includes the key in process arguments or
diagnostic output, and requires `.env.galileo-mcp` and referenced key files to
be owner-only on POSIX systems. Direct HTTP client configs and the bridge send
`Accept: application/json, text/event-stream`; an SSE-only Accept value can be
rejected with HTTP 406 by Galileo.

## Deep Audit Gate

Use `scripts/deep_audit.sh` before declaring the skill correct. It runs:

- Python syntax and `ruff` checks when available
- shell syntax and `shellcheck` checks when available
- render dry-run and full matrix render/validate
- spec-driven render/validate against `template.example`
- generated JSON, JavaScript, and shell validation
- a dependency-free Streamable HTTP bridge check (JSON/SSE, sessions, and no
  `mcp-remote` dependency); the pytest suite adds an end-to-end fake-server test
- generated secret scans
- negative safety checks for direct secret flags and invalid key files
- live MCP server-name/version/tool/schema/prompt/resource drift checks
- a live rendered-bridge initialize/tools/prompts/resources catalog probe using
  a non-secret placeholder header (no tenant tool calls or mutations)
- separate legacy Galileo and post-rename Splunk Agent Observability
  `llms-full.txt` docs-index checks against the product-gap matrix
- a fail-closed release-date check when either docs index contains a release
  newer than the reviewed August 7, 2026 baseline

`--skip-live` uses offline product markers and skips live MCP/network checks.
`--offline-docs` keeps the live MCP check but uses embedded docs markers for
the product coverage audit.

## Secret Handling

The renderer never reads `--galileo-api-key-file`. The optional live auth check
in `probe_mcp.py --auth-check` reads the key file only to call
`GET /v2/current_user`.

The auth check uses a no-redirect opener. Any 3xx is reported as a generic
rejected HTTP status; the API-key header is never replayed to the Location
target and response diagnostics do not contain the key.

Direct secret flags are rejected. Use a chmod-600 file for validation, and use
local client secret stores or `.env.galileo-mcp` for runtime.

## Product Boundary

This skill does not create or manage the complete Galileo platform estate.
Use:

- `galileo-platform-setup` for projects, log streams, datasets, prompts,
  dataset versions/content/collaborators, prompts, experiments, experiment
  groups/ranking, traces/sessions/spans, metrics, preset metric examples,
  metric recomputation, Text-to-SQL metrics, exports, annotations, feedback,
  scorers, Luna/Luna Studio workflows, Protect, Trends, Agent Graph analytics,
  saved views, Python/TypeScript SDK parity, provider integrations, model
  pricing/costs, OTel/OpenInference, and Splunk handoffs.
- `galileo-agent-control-setup` for Agent Control and Cursor hook governance.
- `splunk-hec-service-setup`, `splunk-connect-for-otlp-setup`,
  `splunk-observability-otel-collector-setup`,
  `splunk-observability-dashboard-builder`, and
  `splunk-observability-native-ops` for Splunk-side services.

### July 7-August 7, 2026 boundary details

- **AI Assistant beta** is a read-only console capability using Galileo
  traces, spans, sessions, evaluation scores, and evidence links. Enterprise
  support enablement and a configured LLM integration are prerequisites. No
  public Assistant API or MCP tool is documented. The August 4 release expands
  it across Galileo debugging, and the July 21 release adds signal criticality
  ordering; use `galileo-platform-setup` for readiness, enablement, and console
  evidence.
- **Global dashboards** provide a customizable organization view across
  projects and log streams. The documented Trends endpoints remain scoped to
  `/v2/projects/{project_id}/log_streams/{log_stream_id}/trends...`; do not
  represent them as global-dashboard CRUD. Use `galileo-platform-setup` for UI
  readiness and validation evidence.
- **Generic alert webhooks** are configured in the console with None, Bearer,
  or Basic authentication; credentials are write-only, and the console can
  send a test event. Payload version 1.0 includes event identity, alert, scope,
  observed conditions, deduplication key, deep link, and metadata. No public
  alert/webhook CRUD endpoint or MCP tool is documented. Use
  `galileo-platform-setup`; add a relay if the receiver needs another auth
  scheme.
- **Experiment groups** require Galileo Python SDK 2.2.0 or later and accept an
  optional `experiment_group` in the SDK; create/run calls accept group IDs
  or names. The MCP experiment tool is guidance-only, so lifecycle and ranking
  remain a `galileo-platform-setup` handoff.
- **Large-dataset experiment processing** now batches metric computation for
  datasets with thousands of rows. No exact maximum or client tuning control
  is documented. MCP dataset creation/status is only partial coverage; hand off
  experiment execution, progress, and result validation without inventing a
  hard limit.
- **Annotation Queues** are generally available as of August 4. Public APIs
  cover queue, template, user, record, and export operations, but the observed
  MCP tool catalog has no queue lifecycle tool. Use `galileo-platform-setup`
  for access governance, assignment, annotation, export, and evidence.
- **Metric and cost workflows** added or promoted on July 21 include
  AI-assisted custom-code metric authoring, Model Pricing and Integration Costs
  GA, organization Billing Usage, Trace Count log-stream alerts, and multimodal
  out-of-the-box evaluation metrics. These remain platform/API/console
  handoffs; MCP docs search does not configure them.
- **Hosted models and console presentation** added on August 4 include GPT 5.6
  Sol, Terra, and Luna in supported Galileo surfaces and light, dark, or system
  theme selection. Treat model availability as tenant/platform state and theme
  choice as an operator preference, not MCP server configuration.
- **Naming and documentation epoch** changed on August 7: Galileo is now
  Splunk Agent Observability. `docs.galileo.ai` applies to customers onboarded
  before August 7; later onboarding uses
  `agent-observability-docs.splunk.com`. For onboarding on August 7 itself,
  follow the tenant's linked documentation because the release note does not
  assign that boundary case.

See `references/tool-catalog.md`, `references/client-matrix.md`,
`references/product-gap-matrix.md`, and `references/troubleshooting.md`.
