---
name: splunk-mcp-server-setup
description: >-
  Install, configure, validate, and uninstall the Splunk MCP Server app for
  Cisco Data Fabric agentic/tool access (Splunk_MCP_Server / "Splunk MCP TA").
  Configures mcp.conf server settings, rate limits, encrypted token issuance,
  and renders a shared client bridge bundle that works with Cursor, Codex, and
  Claude Code. Use when the user asks about
  Splunk MCP server setup, Splunk MCP TA, Splunk_MCP_Server, /services/mcp,
  the hosted SCS MCP Gateway for Splunk Observability Cloud, Cursor MCP,
  Codex MCP, Claude Code MCP connectivity to Splunk, or Cisco Data Fabric
  agentic/tool access through Splunk MCP.
---

# Splunk MCP Server Setup

## Shared add-on completion gate

Whenever this workflow installs, configures, or hands off the packaged MCP app,
follow the [shared completion gate](../shared/ta_completion_gate.md). Package
delivery alone is not success; validate the configured endpoint and its data
access, plus any shipped views, or record explicit package evidence that no
dashboards ship.

Automates setup of the **Splunk MCP Server** app (`Splunk_MCP_Server`).

For newer Cisco Data Fabric wording, this is the MCP/tool-access route for
agentic workflows. Federated search, data pipelines, and AI Toolkit workflows
remain in their dedicated skills.

## What This Skill Covers

This skill handles five operator tasks:

1. Install or update the packaged app from the repo-local `splunk-ta/` cache
2. Configure supported runtime settings in `mcp.conf`
3. Mint encrypted bearer tokens into local-only files
4. Render a reusable local bridge bundle for Cursor, Codex, and Claude Code,
   targeting either local Splunk Platform `/services/mcp` or the hosted SCS MCP Gateway
5. Uninstall the app cleanly when lab teardown is needed

The bridge bundle uses the same `mcp-remote` wrapper pattern for all three tools, so
one rendered directory can be opened in Cursor, registered with Codex, and auto-wired
into Claude Code's `.mcp.json`. The wrapper passes header placeholders such as
`${SPLUNK_MCP_HEADER_X_SF_TOKEN}` to `mcp-remote`, keeping token values in the
local env file instead of command argv.

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
- hosted SCS region, Observability realm, and Splunk tenant name

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

Choose one gateway mode:

| Mode | Endpoint | Required secret files |
|------|----------|-----------------------|
| `platform` | Splunk Platform app endpoint, usually `/services/mcp` on port `8089` | encrypted MCP bearer token file when writing a live `.env.splunk-mcp` |
| `o11y` | hosted SCS MCP Gateway | `--o11y-token-file` |
| `combined` | hosted SCS MCP Gateway with Splunk Platform + Observability headers | `--o11y-token-file` and `--splunk-jwt-file` |

Default platform mode preserves the existing local app workflow:

```bash
bash skills/splunk-mcp-server-setup/scripts/setup.sh \
  --render-clients \
  --bearer-token-file /tmp/splunk_mcp.token \
  --cursor-workspace ~/Projects/my-cursor-workspace
```

O11y-only hosted gateway:

```bash
bash skills/splunk-mcp-server-setup/scripts/setup.sh \
  --render-clients \
  --gateway-mode o11y \
  --scs-region pdx10 \
  --o11y-realm us1 \
  --o11y-token-file /tmp/splunk_o11y_api_token
```

Combined Splunk Platform + Observability gateway:

```bash
bash skills/splunk-mcp-server-setup/scripts/setup.sh \
  --render-clients \
  --gateway-mode combined \
  --scs-region pdx10 \
  --o11y-realm us1 \
  --o11y-token-file /tmp/splunk_o11y_api_token \
  --splunk-tenant mytenant \
  --splunk-jwt-file /tmp/splunk_mcp_jwt
```

The SCS gateway URL is derived as:

```text
https://region-<REGION>.api.scs.splunk.com/system/mcp-gateway/v1/
```

Current documented realm-to-SCS-region mappings:

| O11y realm | SCS region |
|------------|------------|
| `eu0` | `dub10` |
| `eu1` | `fra10` |
| `eu2` | `lon10` |
| `us0` | `iad10` |
| `us1` | `pdx10` |
| `us3` | `pdx10` |
| `jp0` | `tyo10` |
| `au0` | `syd10` |
| `sg0` | `sin10` |

Google Cloud Platform realms and GovCloud realms are not supported by the
hosted MCP Gateway; the renderer rejects known unsupported values such as
`us2` and `gov*`. Use `--gateway-url` only when Splunk provides an explicit
gateway endpoint.

Default render target:

```bash
./splunk-mcp-rendered
```

The rendered bundle contains:
- `.cursor/mcp.json` for Cursor
- `run-splunk-mcp.sh` as a shell stdio-to-HTTP bridge
- `run-splunk-mcp.js` as the Node bridge used by Cursor, Codex, and Claude Code registrations
- `.env.splunk-mcp.example`
- `.env.splunk-mcp` when a token file is supplied
- `register-codex-mcp.sh` to sync a portable Codex launcher bundle under `~/.codex/mcp-bridges/`

When `--render-clients` runs, the skill also applies client setup by default:
- registers `CLIENT_NAME` with Codex using a stable home-local launcher copy so repo moves do not break startup
- merges the Splunk MCP entry into `<cursor-workspace>/.cursor/mcp.json`
- writes the Splunk MCP entry into `<workspace>/.mcp.json` for Claude Code
- defaults the workspace target to the current working directory when
  `--cursor-workspace` is omitted

Use `--no-register-codex`, `--no-configure-cursor`, or `--no-configure-claude` to opt
out of any client update while still rendering the bundle.

The shell wrapper expects `mcp-remote` on `PATH`; the Node wrapper used by client
registrations prefers `mcp-remote` on `PATH` and falls back to `npx mcp-remote`.
For `o11y` and `combined` gateway modes, the wrapper also passes
`--transport http-only --allow-http` to match Splunk's hosted gateway examples.

Do not add hosted Observability AI Assistant MCP tools to local
`Splunk_MCP_Server` custom tool manifests. Gateway mode only configures client
headers and endpoint selection.

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
3. **The shared wrapper is the most portable client path**: Cursor, Codex, and
   Claude Code can all use the rendered `run-splunk-mcp.js` bridge via `mcp-remote`.
4. **`mcp.conf` is the supported remote configuration surface**: use it for
   runtime controls such as row limits, TLS verification, and token policy.
5. **The app needs search-tier placement**: it exposes `/services/mcp` and
   depends on custom REST handlers plus KV Store-backed tool metadata.
6. **Hosted SCS MCP Gateway is client-side configuration**: it uses
   `--gateway-mode o11y` or `combined` and does not install hosted
   Observability tools into the local Splunk Platform app.

## Cursor IDE Integration

The repo's `.cursor/mcp.json` points to `splunk-mcp-rendered/run-splunk-mcp.js`.
The bridge wrapper is tracked, but the live `.env.splunk-mcp` token file is
local-only and does not exist until the render/token step runs.

To activate Splunk MCP in Cursor:

1. Complete steps 1–5 above (install, configure, mint token, render bundle).
2. Verify the local token env file exists:
   ```bash
   ls splunk-mcp-rendered/.env.splunk-mcp
   ```
3. Restart or reload Cursor so it picks up the new `.cursor/mcp.json` entry.

If `--cursor-workspace` was used during render, the workspace's own
`.cursor/mcp.json` was also updated. If it was omitted, the repo-root
`.cursor/mcp.json` is the active registration.

## Claude Code Integration

The repo's `.mcp.json` points to `splunk-mcp-rendered/run-splunk-mcp.js`.
The bridge wrapper is tracked, but the live `.env.splunk-mcp` token file is
local-only and does not exist until the render/token step runs.

To activate Splunk MCP in Claude Code:

1. Complete steps 1–5 above (install, configure, mint token, render bundle).
2. Verify the local token env file exists:
   ```bash
   ls splunk-mcp-rendered/.env.splunk-mcp
   ```
3. Restart the Claude Code session so it picks up the `.mcp.json` entry.

The `--render-clients` step writes `.mcp.json` to the target workspace automatically
unless `--no-configure-claude` is passed. If the workspace is the repo root, the
committed `.mcp.json` is updated in place.

## Additional Resources

- [reference.md](reference.md) — endpoint map, config surface, and client notes
- [template.example](template.example) — non-secret intake worksheet
