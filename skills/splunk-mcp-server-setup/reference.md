# Splunk MCP Server Reference

## Core Endpoints

These are the main endpoints surfaced by the packaged app:

| Endpoint | Purpose |
|----------|---------|
| `/services/mcp` | Main MCP HTTP endpoint used by external clients |
| `/servicesNS/nobody/Splunk_MCP_Server/mcp_token` | Mint encrypted bearer tokens and rotate RSA keys |
| `/servicesNS/nobody/Splunk_MCP_Server/mcp_rate_limits` | Read or update effective rate limits |
| `/servicesNS/nobody/Splunk_MCP_Server/mcp_tools` | Custom tool CRUD endpoint |
| `/servicesNS/nobody/Splunk_MCP_Server/mcp_tools/collisions` | Tool-collision analysis endpoint |
| `/.well-known/oauth-protected-resource` | Protected-resource metadata |

## Supported Remote Configuration Surface

The app’s supported remote admin surface is `mcp.conf`.

The setup skill manages these fields:

### `[server]`

- `timeout`
- `max_row_limit`
- `default_row_limit`
- `ssl_verify`
- `require_encrypted_token`
- `legacy_token_grace_days`
- `mcp_token_default_lifetime_seconds`
- `mcp_token_max_lifetime_seconds`
- `token_key_reload_interval_seconds`

### `[rate_limits]`

- `global`
- `admission_global`
- `tenant_authenticated`
- `tenant_unauthenticated`
- `circuit_breaker_failure_threshold`
- `circuit_breaker_cooldown_seconds`

## Local-Only Policy Files

The app loads these directly from the app directory with local-over-default
precedence:

- `safe_spl.json`
- `generating_commands.json`

That means:

- Splunk Enterprise targets you control can override them under
  `$SPLUNK_HOME/etc/apps/Splunk_MCP_Server/local/`
- Splunk Cloud targets should treat those files as package content, not as
  something this repo edits remotely

If you need a stricter SPL whitelist or different excluded built-in tools, plan
that as an app-local overlay or a new vetted package revision.

## Built-In App Characteristics

The packaged app includes:

- custom REST handlers
- KV Store collections `mcp_tools` and `mcp_tools_enabled`
- built-in tool definitions from `default/builtin_tools.json`
- safe-SPL enforcement from `safe_spl.json`

## Cursor And Codex Compatibility Model

The setup skill renders a shared bridge bundle and can then apply that bundle to
both Codex and a real Cursor workspace instead of relying on each IDE’s HTTP
transport details directly.

Rendered files:

| File | Purpose |
|------|---------|
| `.cursor/mcp.json` | Cursor workspace MCP registration (`type: "stdio"`) |
| `run-splunk-mcp.sh` | Stdio wrapper that runs `mcp-remote` against Splunk |
| `.env.splunk-mcp` | Local-only URL and token file consumed by the wrapper |
| `register-codex-mcp.sh` | Registers the same wrapper with `codex mcp add ... -- ./run-splunk-mcp.sh` |

When `--render-clients` is used, the skill:

- renders the reusable bundle above
- registers the wrapper with Codex by default
- merges the Splunk MCP entry into `<cursor-workspace>/.cursor/mcp.json` by default
- defaults the Cursor workspace target to the current working directory when
  `--cursor-workspace` is omitted

Use `--no-register-codex` or `--no-configure-cursor` to skip either auto-apply
step while still rendering the bundle.

This approach is useful because:

- Cursor can use a workspace-local `.cursor/mcp.json` that points at the
  rendered wrapper through `${workspaceFolder}` when the bundle lives inside the
  workspace, or through an absolute path otherwise
- Codex supports stdio MCP servers through `codex mcp add <name> -- <command>`
- the same wrapper can handle `SPLUNK_MCP_INSECURE_TLS=1` for lab certificates

## Wrapper Prerequisite

The rendered wrapper expects `mcp-remote` on `PATH`.

Typical install:

```bash
npm install -g mcp-remote
```

## Recommended Defaults

For a general-purpose admin/search workflow:

- `timeout=90`
- `max_row_limit=2000`
- `default_row_limit=250`
- `require_encrypted_token=true`
- `mcp_token_default_lifetime_seconds=2592000` (30 days)
- `mcp_token_max_lifetime_seconds=7776000` (90 days)
- `global=600`
- `tenant_authenticated=240`
- `tenant_unauthenticated=60`

## Operational Notes

- `mcp_token` requires the `mcp_tool_admin` capability
- `mcp_token` minting and RSA key rotation fail closed with HTTP 412 when
  `require_encrypted_token=false`
- the packaged `authorize.conf` grants that capability to `admin` and `sc_admin`
- app visibility may need to be forced to `true` after ACS install
- `/services/mcp` is exposed on the Splunk management port, typically `8089`
