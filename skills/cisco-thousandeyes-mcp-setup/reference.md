# Cisco ThousandEyes MCP Server Setup Reference

## Source guidance

- Official MCP docs: `docs.thousandeyes.com/product-documentation/integration-guides/thousandeyes-mcp-server`
- Cursor Marketplace plugin (turnkey alternative for Cursor): `cursor.com/marketplace/cisco-thousand-eyes`
- TE rate limits: `developer.cisco.com/docs/thousandeyes/rate-limits/`
- Existing Codex MCP registration pattern in this repo: [agent/register-codex-splunk-cisco-skills-mcp.sh](../../agent/register-codex-splunk-cisco-skills-mcp.sh)

## Rendered layout

By default, assets are written under `cisco-thousandeyes-mcp-rendered/`:

- `mcp/cursor.mcp.json` — Cursor MCP config with optional Marketplace plugin link.
- `mcp/claude.mcp.json` — Claude Code custom-connector flow doc + JSON.
- `mcp/codex-register-te-mcp.sh` — Codex registration shell.
- `mcp/vscode.mcp.json` — VS Code MCP config with `${input:te-key}` prompt-string pattern.
- `mcp/kiro.mcp.json` — AWS Kiro MCP config via `mcp-remote@latest`.
- `mcp/README.md` — per-client install steps + rate-limit notes + write-tool warnings.
- `metadata.json` — non-secret plan summary.

## Setup modes

`setup.sh` supports these mode flags:

- `--render` — render client configurations (default if no mode given).
- `--apply` — render, then surface the per-client copy commands. The script does NOT execute the copies; the operator runs them after review.
- `--validate` — run static validation against an already-rendered output directory.
- `--dry-run` — show the plan without writing files.
- `--json` — emit JSON dry-run output.
- `--explain` — print plan in plain English (no API calls or writes).

## Required values

`--client LIST` is always required. Comma-separated subset of `cursor,claude,codex,vscode,kiro`.

`--auth` defaults to `bearer`. Use `--auth oauth2` to render the OAuth2 client flow (browser consent on first connection; no token file needed).

For `--auth bearer`, `--te-token-file` should point at a chmod-600 file containing the TE API token. The renderer never reads this file — it surfaces the path in the rendered Codex script and in the README only.

## Secret handling

Supported secret-file flag:

- `--te-token-file`

Rejected direct-secret flags (each maps to `--te-token-file`):

- `--te-token`
- `--access-token`
- `--token`
- `--bearer-token`
- `--api-token`

Cursor configs use `${env:TE_API_TOKEN}` so the token is supplied via the operator's shell environment. VS Code uses `${input:te-key}` for a runtime password prompt. Codex uses the token file at registration time. Kiro uses either OAuth2 (browser flow) or `${env:TE_API_TOKEN}` plus `mcp-remote@latest` `--header`.

## Tool catalog

The official ThousandEyes MCP Server exposes two tool groups. The skill always renders the read-only group; the write group requires `--accept-te-mcp-write-tools`.

**Read-only (auto-allow recommended)**:

- List Tests / Get Test Details
- List Events / Get Event Details
- List Alerts / Get Alert Details
- Search Outages
- Get Anomalies, Get Metrics, Get Service Map, Views Explanations
- List Endpoint Agents and Tests / Get Endpoint Agent Metrics / Get Connected Device
- Get Cloud and Enterprise Agents
- Get Path Visualization / Get Full Path Visualization / Get BGP Test Results / Get BGP Route Details
- Get Account Groups / Search Templates

**Write / Instant-Test (requires `--accept-te-mcp-write-tools`)**:

- Create / Update / Delete Synthetic Test
- Run Instant Test
- Deploy Template

**Run Instant Test consumes ThousandEyes units identically to scheduled tests.** The rendered README always surfaces this warning.

## Rate limits

- OAuth Bearer Token usage shares the org-wide 240 req/min limit with every integration using a standard API token.
- OAuth2 client flow: each OAuth2 client gets its own 240 req/min limit. Recommended for shared TE orgs with multiple AI assistants.

## Hand-offs

- TE → Splunk Observability Cloud telemetry wiring → `splunk-observability-thousandeyes-integration` (OpenTelemetry stream, Integrations 2.0 APM connector, full TE asset lifecycle).
- Splunk Platform `ta_cisco_thousandeyes` add-on → `cisco-thousandeyes-setup` (HEC streaming inputs, OAuth device flow, indexes/sourcetypes).

See `references/clients.md` for the per-client install matrix, `references/tool-catalog.md` for the full tool inventory, and `references/troubleshooting.md` for diagnostic commands.
