# Galileo MCP Server Setup Reference

## Source Guidance

- Galileo MCP Server docs:
  `https://docs.galileo.ai/getting-started/mcp/setup-galileo-mcp`
- Galileo docs coverage index:
  `https://docs.galileo.ai/llms-full.txt`
- MCP tool-call logging:
  `https://docs.galileo.ai/how-to-guides/basics/log-mcp-server-calls/log-mcp-server-calls`
- Galileo Logger:
  `https://docs.galileo.ai/sdk-api/logging/galileo-logger`
- Integrations overview:
  `https://docs.galileo.ai/sdk-api/third-party-integrations/overview`
- Agentic metrics:
  `https://docs.galileo.ai/concepts/metrics/agentic/agentic-overview`
- SDK example:
  `https://github.com/rungalileo/sdk-examples/tree/main/python/logging-samples/log-mcp-calls`

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

For self-hosted Galileo, derive the URL from the console URL by replacing the
first `console` label with `api` and appending `/mcp/http/mcp`. Examples:

- `https://console.galileo.example.com` ->
  `https://api.galileo.example.com/mcp/http/mcp`
- `https://console-galileo.apps.mycompany.com` ->
  `https://api-galileo.apps.mycompany.com/mcp/http/mcp`

## Setup Modes

- `--render`: render client configuration and handoff files.
- `--validate`: run static validation against rendered files.
- `--probe`: run a live no-secret MCP metadata probe.
- `--doctor`: render, validate, and probe.
- `--dry-run`: print the render plan without writing files.
- `--json`: emit JSON for dry-run and probe summaries.
- `--spec`: read the non-secret YAML/JSON intake file; command-line flags
  override spec values.

No mode writes into real Cursor, VS Code, Codex, Claude, or Kiro config paths.

## Deep Audit Gate

Use `scripts/deep_audit.sh` before declaring the skill correct. It runs:

- Python syntax and `ruff` checks when available
- shell syntax and `shellcheck` checks when available
- render dry-run and full matrix render/validate
- spec-driven render/validate against `template.example`
- generated JSON, JavaScript, and shell validation
- generated secret scans
- negative safety checks for direct secret flags and invalid key files
- live MCP name/tool/schema/prompt/resource drift checks
- Galileo `llms-full.txt` docs-index to product-gap-matrix coverage checks

`--skip-live` uses offline product markers and skips live MCP/network checks.
`--offline-docs` keeps the live MCP check but uses embedded docs markers for
the product coverage audit.

## Secret Handling

The renderer never reads `--galileo-api-key-file`. The optional live auth check
in `probe_mcp.py --auth-check` reads the key file only to call
`GET /v2/current_user`.

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

See `references/tool-catalog.md`, `references/client-matrix.md`,
`references/product-gap-matrix.md`, and `references/troubleshooting.md`.
