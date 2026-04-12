---
name: splunk-mcp-server-setup
description: >-
  Install, configure, validate, and uninstall the Splunk MCP Server app
  (Splunk_MCP_Server / "Splunk MCP TA"). Configures mcp.conf server settings,
  rate limits, encrypted token issuance, and renders a shared client bridge
  bundle that works with both Cursor and Codex. Use when the user asks about
  Splunk MCP server setup, Splunk MCP TA, Splunk_MCP_Server, /services/mcp,
  Cursor MCP, or Codex MCP connectivity to Splunk.
---

# Splunk MCP Server Setup

Automates setup of the **Splunk MCP Server** app (`Splunk_MCP_Server`).

## What This Skill Covers

This skill handles five operator tasks:

1. Install or update the packaged app from the repo-local `splunk-ta/` cache
2. Configure supported runtime settings in `mcp.conf`
3. Mint encrypted bearer tokens into local-only files
4. Render a reusable local bridge bundle for both Cursor and Codex
5. Uninstall the app cleanly when lab teardown is needed

The bridge bundle uses the same `mcp-remote` wrapper pattern for both tools, so
one rendered directory can be opened in Cursor and also registered with Codex.

## Package Model

**Use the repo-local package in `splunk-ta/` as the default install source.**

The packaged app currently lives in:

```bash
splunk-ta/splunk-mcp-server_110.tgz
```

Install it with the shared installer:

```bash
bash skills/splunk-app-install/scripts/install_app.sh \
  --source local \
  --file splunk-ta/splunk-mcp-server_110.tgz
```

Or let this skill do the install/update step for you:

```bash
bash skills/splunk-mcp-server-setup/scripts/setup.sh --install
```

To remove the app again:

```bash
bash skills/splunk-mcp-server-setup/scripts/setup.sh --uninstall
```

## Agent Behavior — Credentials And Tokens

**The agent must NEVER ask for passwords, bearer tokens, or other secrets in chat.**

Splunk credentials come from the project-root `credentials` file (falls back to
`~/.splunk/credentials`):

```bash
bash skills/shared/scripts/setup_credentials.sh
```

MCP bearer tokens are secrets. Always write them to a local-only file:

```bash
bash skills/splunk-mcp-server-setup/scripts/setup.sh \
  --token-user "${SPLUNK_USER}" \
  --write-token-file /tmp/splunk_mcp.token
```

The agent may freely ask for non-secret values such as:
- MCP token username
- desired token lifetime
- row limits
- rate-limit thresholds
- whether the rendered client bridge should assume insecure TLS for lab use

Use an existing Splunk user that has the `mcp_tool_admin` capability. In most
lab setups that should be the same account already configured in
`SPLUNK_USER`.

For prerequisite collection, use
`skills/splunk-mcp-server-setup/template.example` as the intake worksheet and
keep any filled copy local as `template.local`.

## Environment

| Item | Value |
|------|-------|
| Search-tier API | `SPLUNK_SEARCH_API_URI` env var (legacy alias: `SPLUNK_URI`) |
| Cloud stack | `SPLUNK_CLOUD_STACK` for Splunk Cloud |
| App name | `Splunk_MCP_Server` |
| Local package | `splunk-ta/splunk-mcp-server_110.tgz` |
| Credentials | Project-root `credentials` file (falls back to `~/.splunk/credentials`) |
| Skill scripts | `skills/splunk-mcp-server-setup/scripts/` |

## Setup Workflow

### Step 1: Install Or Update The App

```bash
bash skills/splunk-mcp-server-setup/scripts/setup.sh --install
```

The setup script detects whether `Splunk_MCP_Server` is already installed and
uses the shared app installer in install or update mode automatically.

### Alternative: Uninstall The App

```bash
bash skills/splunk-mcp-server-setup/scripts/setup.sh --uninstall
```

This delegates to the shared app uninstaller for `Splunk_MCP_Server` and
restarts Splunk automatically on Enterprise targets unless the shared workflow
is changed to skip restart. Run `--uninstall` by itself; do not combine it with
render, token, or configuration flags.

### Step 2: Configure Supported MCP Server Settings

```bash
bash skills/splunk-mcp-server-setup/scripts/setup.sh \
  --timeout 90 \
  --max-row-limit 2000 \
  --default-row-limit 250 \
  --require-encrypted-token true \
  --token-default-lifetime-seconds 2592000 \
  --token-max-lifetime-seconds 7776000 \
  --global-rate-limit 600 \
  --tenant-authenticated 240 \
  --tenant-unauthenticated 60
```

This updates supported fields in `mcp.conf`:
- `[server] timeout`
- `[server] max_row_limit`
- `[server] default_row_limit`
- `[server] ssl_verify`
- `[server] require_encrypted_token`
- `[server] legacy_token_grace_days`
- `[server] mcp_token_default_lifetime_seconds`
- `[server] mcp_token_max_lifetime_seconds`
- `[server] token_key_reload_interval_seconds`
- `[rate_limits]` admission and circuit-breaker values

The script also fixes `visible=true` on the app if ACS or local installs left it
hidden in Splunk Web.

### Step 3: Optionally Rotate The MCP RSA Keys

```bash
bash skills/splunk-mcp-server-setup/scripts/setup.sh \
  --rotate-keys \
  --rotate-key-size 4096
```

### Step 4: Mint An Encrypted Bearer Token

```bash
bash skills/splunk-mcp-server-setup/scripts/setup.sh \
  --token-user "${SPLUNK_USER}" \
  --token-expires-on +30d \
  --write-token-file /tmp/splunk_mcp.token
```

The script writes the encrypted token to the target file with `0600`
permissions. It does not print the token to stdout.

If you disable `require_encrypted_token`, the app intentionally fails closed on
`/mcp_token` minting and key rotation. Do not combine
`--require-encrypted-token false` with `--write-token-file` or `--rotate-keys`
in the same run.

### Step 5: Render And Apply The Shared Cursor/Codex Bridge Bundle

```bash
bash skills/splunk-mcp-server-setup/scripts/setup.sh \
  --render-clients \
  --bearer-token-file /tmp/splunk_mcp.token \
  --cursor-workspace ~/Projects/my-cursor-workspace
```

Default render target:

```bash
./splunk-mcp-rendered
```

The rendered bundle contains:
- `.cursor/mcp.json` for Cursor
- `run-splunk-mcp.sh` for the stdio-to-HTTP bridge
- `.env.splunk-mcp.example`
- `.env.splunk-mcp` when a token file is supplied
- `register-codex-mcp.sh` to sync a portable Codex launcher bundle under `~/.codex/mcp-bridges/`

When `--render-clients` runs, the skill now also applies client setup by
default:
- registers `CLIENT_NAME` with Codex using a stable home-local launcher copy so repo moves do not break startup
- merges the Splunk MCP entry into `<cursor-workspace>/.cursor/mcp.json`
- defaults the Cursor workspace target to the current working directory when
  `--cursor-workspace` is omitted

Use `--no-register-codex` or `--no-configure-cursor` to opt out of either
client update while still rendering the bundle.

`mcp-remote` must be on `PATH` for the wrapper script and auto-applied client
registrations to work.

### Step 6: Validate

```bash
bash skills/splunk-mcp-server-setup/scripts/validate.sh
```

Checks:
- app installed and visible
- `/services/mcp` responds to a JSON-RPC `ping`
- key MCP REST endpoints respond
- protected-resource metadata endpoint is reachable when configured
- current server settings and rate-limit values are readable
- derived `/services/mcp` URL is sane

## Local-Only Policy Overlays

Two important policy files are **not** exposed through a safe remote admin API
in this app:

- `local/safe_spl.json`
- `local/generating_commands.json`

Those files must be managed as app-local overlays on targets where you control
the filesystem. On Splunk Cloud, treat those as package-content concerns rather
than something this repo silently edits in place.

See [reference.md](reference.md) for the exact implications.

## Key Learnings / Known Issues

1. **`safe_spl.json` is local-only**: the app loads it from the app directory,
   not from a custom REST config endpoint.
2. **Token output is secret material**: write encrypted bearer tokens to local
   files, never to chat or tracked repo files.
3. **The shared wrapper is the most portable client path**: both Cursor and
   Codex can use the rendered `run-splunk-mcp.sh` bridge via `mcp-remote`.
4. **`mcp.conf` is the supported remote configuration surface**: use it for
   runtime controls such as row limits, TLS verification, and token policy.
5. **The app needs search-tier placement**: it exposes `/services/mcp` and
   depends on custom REST handlers plus KV Store-backed tool metadata.

## Cursor IDE Integration

The repo's `.cursor/mcp.json` points to `splunk-mcp-rendered/run-splunk-mcp.sh`.
**This path does not exist until the render step runs.** Cursor will silently
skip the MCP server if the path is missing.

To activate Splunk MCP in Cursor:

1. Complete steps 1–5 above (install, configure, mint token, render bundle).
2. Verify the rendered path exists:
   ```bash
   ls splunk-mcp-rendered/run-splunk-mcp.sh
   ```
3. Restart or reload Cursor so it picks up the new `.cursor/mcp.json` entry.

If `--cursor-workspace` was used during render, the workspace's own
`.cursor/mcp.json` was also updated. If it was omitted, the repo-root
`.cursor/mcp.json` is the active registration.

## Additional Resources

- [reference.md](reference.md) — endpoint map, config surface, and client notes
- [template.example](template.example) — non-secret intake worksheet
