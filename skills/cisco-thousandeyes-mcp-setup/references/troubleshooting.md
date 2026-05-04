# Troubleshooting

## `command not found: npx`

Several MCP clients (Codex via `mcp-remote@latest`, AWS Kiro, sometimes VS Code) require Node.js / npx on PATH.

```bash
node --version
npx --version
```

Install Node.js: `https://nodejs.org/en/download`. After installation, restart the MCP client.

## `command not found: codex`

Install or update the Codex CLI: see `https://docs.cursor.com/codex` (or your org's distribution channel). After installation:

```bash
codex --version
codex mcp list
```

## Authentication errors against `https://api.thousandeyes.com/mcp`

- Verify the API token with a temporary `curl` config so the token stays out of argv:

  ```bash
  TE_CURL_CONFIG="$(mktemp)"
  chmod 600 "$TE_CURL_CONFIG"
  { printf 'header = "Authorization: Bearer '; tr -d '\r\n' < /tmp/te_api_token; printf '"\n'; } > "$TE_CURL_CONFIG"
  curl -sS -K "$TE_CURL_CONFIG" https://api.thousandeyes.com/v7/account-groups
  rm -f "$TE_CURL_CONFIG"
  ```

- Verify the token is associated with a user that holds the `API Access` permission (per `docs.thousandeyes.com/.../user-management/authorization/rb-access-control`).
- Confirm the org has not opted out of TE AI features (per the MCP doc prerequisites section).

## Rate limit errors (`429 Too Many Requests`)

- OAuth Bearer Token mode shares the org-wide 240 req/min limit. Multiple AI assistants on the same token can saturate it quickly.
- Switch to OAuth2 client flow (`--auth oauth2`); each OAuth2 client gets its own 240 req/min budget.
- Contact ThousandEyes Support for a higher limit if neither approach is sufficient.

## "No tools available" in the AI client after registration

- Verify the client successfully connected: most MCP clients log the initial handshake.
- For Cursor: View > Output > MCP Logs.
- For Claude Desktop: ensure the connector status shows `Connected` in Settings > Connectors.
- For Codex: `codex mcp get ThousandEyes --json`; check the `status` field.
- For VS Code: verify the `${input:te-key}` prompt fired and the token was supplied.

## Write tools missing after `--accept-te-mcp-write-tools`

- Cursor: confirm the per-tool gating UI shows the Create/Update/Delete + Run Instant Test + Deploy Template tools as Auto-allow or Manual.
- Claude: enable the tools in the connector's Configure > Tool permissions panel.
- Codex / VS Code / Kiro: these clients don't currently expose per-tool toggles in the rendered config; the operator must rely on the AI assistant's native approval prompts.

## Instant Test ran when not intended

- Run Instant Test consumes TE units **identically to scheduled tests**. If an unintended Instant Test ran, review:
  - Cursor / Claude per-tool approval setting (don't auto-allow Run Instant Test).
  - Operator prompt phrasing — words like "test", "check", or "probe" can trigger the AI assistant to call Run Instant Test if not gated.
- The TE bill reflects the consumption; there is no rollback. Lower the per-tool approval to Manual and review the next prompt before approval.

## Removing the MCP registration

- Cursor: delete the entry from `~/.cursor/mcp.json` (or `<repo>/.cursor/mcp.json`).
- Claude: Settings > Connectors > ThousandEyes MCP Server > Remove.
- Codex: `codex mcp remove ThousandEyes`.
- VS Code: remove the entry from your MCP servers config.
- Kiro: delete the entry from `~/.kiro/settings/mcp.json`.

## Diagnostic probe

```bash
curl -s -o /dev/null -w '%{http_code}\n' --max-time 10 https://api.thousandeyes.com/mcp
# 401 expected without Authorization (the endpoint is reachable; auth is required for tool calls)

TE_CURL_CONFIG="$(mktemp)"
chmod 600 "$TE_CURL_CONFIG"
{ printf 'header = "Authorization: Bearer '; tr -d '\r\n' < /tmp/te_api_token; printf '"\n'; } > "$TE_CURL_CONFIG"

curl -K "$TE_CURL_CONFIG" \
  -s -o /dev/null -w '%{http_code}\n' --max-time 10 \
  https://api.thousandeyes.com/v7/account-groups
rm -f "$TE_CURL_CONFIG"
# 200 confirms the token is valid for the v7 REST API; MCP uses the same auth scope.
```
