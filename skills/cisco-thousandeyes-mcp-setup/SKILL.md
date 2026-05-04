---
name: cisco-thousandeyes-mcp-setup
description: >-
  Render and (optionally) apply Model Context Protocol client configurations
  for the official ThousandEyes MCP Server (https://api.thousandeyes.com/mcp,
  GA per docs.thousandeyes.com/.../thousandeyes-mcp-server). Supports Cursor,
  Claude Code, Codex, VS Code, and AWS Kiro clients with both OAuth Bearer and
  OAuth2 flows. Surfaces TE rate limits, the unit-consumption warning for
  Instant Tests, and gates the write/Instant-Test tool group behind an
  explicit opt-in. Use when the user asks to register the ThousandEyes MCP,
  set up TE in Cursor/Claude/Codex/VS Code/Kiro, configure the Cisco
  ThousandEyes Cursor plugin, or pair an AI assistant with TE.
---

# Cisco ThousandEyes MCP Server Setup

This skill is **agent-tooling only** — it does not move telemetry. For TE → Splunk Observability Cloud wiring (OpenTelemetry stream, Integrations 2.0 APM connector, full TE asset lifecycle), use `splunk-observability-thousandeyes-integration`. For the Splunk Platform `ta_cisco_thousandeyes` add-on, use `cisco-thousandeyes-setup`.

## Overview

Render per-client MCP configurations for the official **ThousandEyes MCP Server** at `https://api.thousandeyes.com/mcp`. Optionally apply the configurations into the user's actual Cursor / Claude Code / Codex / VS Code / AWS Kiro config locations.

Render-first by default. `--apply` only writes to user config files when explicitly requested.

## Safety Rules

- Never ask for the ThousandEyes API token in conversation.
- Never pass the token on the command line or as an environment-variable prefix.
- Use `--te-token-file` for the Bearer header path; the renderer never reads the token file.
- Reject direct token flags (`--te-token`, `--access-token`, `--token`, `--bearer-token`, `--api-token`).
- Token files must be `chmod 600`. `--apply` runs a permission preflight and aborts with a `chmod 600 <path>` hint when looser. `--allow-loose-token-perms` overrides with a `WARN`.
- Cursor and VS Code configs use `${input:te-key}` prompt-string patterns or environment variables, never inline tokens. Codex should use OAuth2 browser consent unless a client-side secret store can inject Bearer headers without argv exposure. Claude Code uses an OAuth-pair browser flow.
- The write/Instant-Test tool group (`Create/Update/Delete Synthetic Test`, `Run Instant Test`, `Deploy Template`) is **never** enabled by default. Pass `--accept-te-mcp-write-tools` to allow it in clients that support per-tool gating; the rendered README always surfaces the unit-consumption warning.

## Primary Workflow

1. Decide which clients to register and which auth flow to use:

   - **OAuth Bearer Token**: simplest; one shared token file per client. Counts against the org-wide 240 req/min rate limit.
   - **OAuth2 client**: per-client OAuth2 flow with browser consent. Each OAuth2 client gets its own 240 req/min limit (recommended when multiple AI assistants share an org).

2. Render:

   ```bash
   bash skills/cisco-thousandeyes-mcp-setup/scripts/setup.sh \
     --render \
     --client cursor,claude,codex,vscode,kiro \
     --auth bearer \
     --te-token-file /tmp/te_api_token \
     --output-dir cisco-thousandeyes-mcp-rendered
   ```

3. Review `cisco-thousandeyes-mcp-rendered/`:

   - `mcp/cursor.mcp.json`
   - `mcp/claude.mcp.json`
   - `mcp/codex-register-te-mcp.sh`
   - `mcp/vscode.mcp.json`
   - `mcp/kiro.mcp.json`
   - `mcp/README.md` — per-client install instructions, rate-limit notes, unit-consumption warnings
   - `metadata.json`

4. Apply only when explicitly requested. `--apply` writes the rendered configs into the user's actual config locations (after a confirmation prompt) and runs the Codex registration helper:

   ```bash
   bash skills/cisco-thousandeyes-mcp-setup/scripts/setup.sh \
     --apply \
     --client cursor,claude,codex,vscode,kiro \
     --auth bearer \
     --te-token-file /tmp/te_api_token
   ```

## Tool Group Gating

The official ThousandEyes MCP Server exposes two tool groups:

- **Read-only tools** (auto-allowed): List/Get Tests, List/Get Events, List/Get Alerts, Search Outages, Get Anomalies, Get Metrics, Get Service Map, Views Explanations, Endpoint Agent Metrics + Connected Device, Cloud/Enterprise Agents, Get Path / Full Path / BGP Test Results / BGP Route Details, Get Account Groups, Search/Deploy Templates (Search only).
- **Write/Instant-Test tools** (require `--accept-te-mcp-write-tools`): Create/Update/Delete Synthetic Test, Run Instant Test, Deploy Template.

**Unit consumption.** Run Instant Test consumes ThousandEyes units identically to scheduled tests. The rendered README always surfaces this warning, and `--apply` refuses to enable write tools without `--accept-te-mcp-write-tools`.

## Hand-offs

- TE → Splunk Observability Cloud wiring → `splunk-observability-thousandeyes-integration` (OpenTelemetry stream, Integrations 2.0 APM connector, full TE asset lifecycle).
- Splunk Platform `ta_cisco_thousandeyes` add-on → `cisco-thousandeyes-setup` (HEC streaming inputs, OAuth device flow, indexes/sourcetypes).

## Validation

```bash
bash skills/cisco-thousandeyes-mcp-setup/scripts/validate.sh
```

Static checks confirm every selected client has a renderable config; verifies no token material was written to any rendered file. Use `--live` after `--apply` to reach `https://api.thousandeyes.com/mcp` from each client config.

See `reference.md` for option details and `references/clients.md` for the per-client install matrix.
