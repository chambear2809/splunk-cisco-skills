# Splunk MCP Server Reference

## Supported Package And Provenance

This skill supports the official [Splunk MCP Server 1.3.1 package from
Splunkbase app 7931](https://splunkbase.splunk.com/app/7931). The matching
[Splunk 1.3 release notes](https://help.splunk.com/en/splunk-cloud-platform/mcp-server-for-splunk-platform/1.3/mcp-server-release-notes)
describe the supported 1.3.x behavior.

| Property | Required value |
|----------|----------------|
| Splunkbase app ID | `7931` |
| Package directory | `Splunk_MCP_Server` |
| App version | `1.3.1` |
| Default local cache | `splunk-ta/splunk-mcp-server_131.tgz` |
| SHA-256 | `fa380909ba24dcea155d59f9dccc67fd83d99b1d9595681183c6467bacdf70d3` |
| Provenance | Official Splunkbase app 7931 download; do not use a repacked or unverified archive |
| Production approval | **Blocked pending vendor security fixes** |

The package cache is intentionally ignored by Git. The tracked
`package-manifest.json` is the authoritative version, filename, and checksum
record. `setup.sh` verifies version `1.3.1` and the checksum above for every
supplied archive, including `--package-file` overrides.

Version 1.3.1 remains useful for isolated compatibility testing, but it is not
a production-approved release. Setup blocks installation, local configuration,
key rotation, token minting, and local Platform client activation by default;
`--completion` cannot certify this release. The explicit
`--accept-nonproduction-package` override records lab intent; it is not a
remediation.

## Core Endpoints

These are the main endpoints surfaced by the packaged app:

| Endpoint | Purpose |
|----------|---------|
| `/services/mcp` | Main MCP HTTP endpoint used by external clients |
| `https://region-<REGION>.api.scs.splunk.com/system/mcp-gateway/v1/` | Hosted SCS MCP Gateway endpoint for Splunk Observability Cloud tools |
| `/servicesNS/nobody/Splunk_MCP_Server/mcp_token` | `GET` mints encrypted bearer tokens; `POST action=rotate` rotates RSA keys in 1.3.1 |
| `/servicesNS/nobody/Splunk_MCP_Server/mcp_rate_limits` | Read or update effective rate limits |
| `/servicesNS/nobody/Splunk_MCP_Server/mcp_tools` | Custom tool CRUD endpoint |
| `/servicesNS/nobody/Splunk_MCP_Server/mcp_tools/collisions` | Tool-collision analysis endpoint |
| `/servicesNS/nobody/Splunk_MCP_Server/mcp_tool_roles` | Version 1.3 role-to-tool mapping administration |
| `/servicesNS/nobody/Splunk_MCP_Server/mcp_guardrails` | Version 1.3 guardrail administration |
| `/servicesNS/nobody/Splunk_MCP_Server/allowed_spl_cmds` | Version 1.3 allowed SPL command administration |
| `/.well-known/oauth-protected-resource` | Protected-resource metadata |

## Supported Remote Configuration Surface

The app’s supported remote admin surface is `mcp.conf`.

The setup skill manages these fields:

### `[server]`

- `timeout`
- `max_row_limit`
- `default_row_limit`
- `ssl_verify` (stored for forward compatibility, but **not enforced by vendor
  release 1.3.1**; it is not a verified TLS control)
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

## Policy Files And 1.3 Administration Surfaces

The app loads these directly from the app directory with local-over-default
precedence:

- `safe_spl.json`
- `generating_commands.json`

That means:

- Splunk Enterprise targets you control can override them under
  `$SPLUNK_HOME/etc/apps/Splunk_MCP_Server/local/`
- Splunk Cloud targets should treat those files as package content, not as
  something this repo edits remotely

Version 1.3.1 adds authenticated administration surfaces for allowed SPL
commands, tool-role mappings, and guardrails. The skill validates those
endpoints but does not mutate their policies. Role assignments and additions to
the allowed-command set require separate operator review.

Do not use `exclude_tools` to disable tools in release 1.3.1. The vendor code
incorrectly interprets that list as a Safe-SPL validation bypass. Disable tools
through `mcp_tools_enabled` only, and do not expose query-capable tools to
untrusted callers until the vendor fixes and regression-tests this behavior.
A stricter SPL whitelist must be delivered as a reviewed app-local overlay or a
new vetted package revision.

## Built-In App Characteristics

The packaged app includes:

- custom REST handlers
- KV Store collections `mcp_tools`, `mcp_tools_enabled`, and `mcp_tool_roles`
- built-in tool definitions from `default/builtin_tools.json`
- safe-SPL enforcement from `safe_spl.json`
- authenticated tool-role, guardrail, and allowed-command REST handlers
- the `dashboard`, `monitoring`, `tools`, and `tool_settings` Splunk Web views

## Cursor, Codex, And Claude Code Compatibility Model

The setup skill renders a shared bridge bundle and can then apply that bundle to
Codex, a real Cursor workspace, and a Claude Code project instead of relying on
each tool’s HTTP transport details directly.

Supported gateway modes:

| Mode | URL source | Headers |
|------|------------|---------|
| `platform` | `--mcp-url` or derived `<SPLUNK_URI>/services/mcp` | `Authorization: Bearer ${SPLUNK_MCP_TOKEN}` |
| `o11y` | `--gateway-url` or `--scs-region` derived hosted gateway URL | `X-SF-TOKEN`, `X-SF-REALM` |
| `combined` | `--gateway-url` or `--scs-region` derived hosted gateway URL | `Authorization`, `splunk_tenant`, `X-SF-TOKEN`, `X-SF-REALM` |

Splunk has deprecated the legacy hosted SCS MCP Gateway for new deployments.
Use `o11y` or `combined` only for an existing endpoint explicitly provided by
Splunk; use `platform` and the Splunkbase app for new Splunk Platform MCP
deployments.

The rendered wrappers pass literal `${VAR}` placeholders to `mcp-remote` in
each `--header` value. `mcp-remote` expands those placeholders from the
wrapper environment at runtime, so token values stay in `.env.splunk-mcp` and
do not appear in process argv. Hosted gateway modes add the transport flags
required by the SCS endpoint, but the renderer still requires an HTTPS target.

Remote endpoints must use HTTPS with a trusted certificate. Explicit HTTP and
`--client-insecure-tls` are accepted only for loopback targets such as
`localhost`, `127.0.0.1`, or `::1`; do not use them to bypass certificate
validation for a remote Splunk deployment.

Current hosted gateway region mapping:

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
hosted gateway. The setup renderer rejects known unsupported values such as
`us2`, `gov*`, and values containing `gcp`.

Rendered files:

| File | Purpose |
|------|---------|
| `.cursor/mcp.json` | Cursor workspace MCP registration (`type: "stdio"`) |
| `run-splunk-mcp.sh` | Shell wrapper that runs `mcp-remote` against Splunk |
| `run-splunk-mcp.js` | Node stdio wrapper used by Cursor, Codex, and Claude Code registrations |
| `.env.splunk-mcp` | Local-only URL and token file consumed by the wrapper |
| `register-codex-mcp.sh` | Syncs a portable launcher bundle into `~/.codex/mcp-bridges/<name>/` and registers that wrapper with Codex |

When `--render-clients` is used, the skill:

- renders the reusable bundle above
- registers a stable home-local wrapper copy with Codex by default
- merges the Splunk MCP entry into `<cursor-workspace>/.cursor/mcp.json` by default
- writes the Splunk MCP entry into `<workspace>/.mcp.json` for Claude Code by default
- defaults the workspace target to the current working directory when
  `--cursor-workspace` is omitted

Use `--no-register-codex`, `--no-configure-cursor`, or `--no-configure-claude` to
skip any auto-apply step while still rendering the bundle.

This approach is useful because:

- Cursor can use a workspace-local `.cursor/mcp.json` that points at the
  rendered wrapper through `${workspaceFolder}` when the bundle lives inside the
  workspace, or through an absolute path otherwise
- Codex can keep using stdio MCP registration without pinning the command to a repo checkout path
- Claude Code reads `.mcp.json` at the project root and uses the same stdio wrapper
- loopback-only lab targets can use `SPLUNK_MCP_INSECURE_TLS=1`

Gateway mode does not alter local `Splunk_MCP_Server` custom tool manifests.
External hosted Observability AI Assistant MCP tools remain served by Splunk's
hosted gateway rather than by local Splunk Platform app content.

## Wrapper Prerequisite

The shell and Node wrappers require an operator-vetted `mcp-remote@0.1.38` on
`PATH`. They fail closed when it is absent and never fall back to `npx` or
download code at startup.

The upstream package describes `mcp-remote` as an experimental compatibility
proxy. Prefer a client's native Streamable HTTP transport when it supports the
required headers. Pinning and metadata verification reduce supply-chain drift;
they do not turn the proxy into a production assurance boundary.

Install the pinned version before registering a client:

```bash
npm install -g mcp-remote@0.1.38
```

## Recommended Defaults

For a general-purpose admin/search workflow:

- `timeout=90`
- `max_row_limit=2000`
- `default_row_limit=250`
- `ssl_verify=true` (configuration intent only; 1.3.1 does not enforce it)
- `require_encrypted_token=true`
- `legacy_token_grace_days=0`
- `mcp_token_default_lifetime_seconds=43200` (12 hours)
- `mcp_token_max_lifetime_seconds=86400` (24 hours)
- `token_key_reload_interval_seconds=300`
- `global=600`
- `admission_global=60`
- `tenant_authenticated=240`
- `tenant_unauthenticated=10`
- `circuit_breaker_failure_threshold=5`
- `circuit_breaker_cooldown_seconds=60`

## Operational Notes

- `mcp_token` requires the `mcp_tool_admin` capability
- `mcp_token` minting and RSA key rotation fail closed with HTTP 412 when
  `require_encrypted_token=false`
- the packaged `authorize.conf` grants that capability to `admin` and `sc_admin`
- app visibility may need to be forced to `true` after ACS install
- `/services/mcp` is exposed on the Splunk management port, typically `8089`
- live hosted-gateway validation should use standard MCP JSON-RPC calls such
  as `tools/list` and then `tools/call` against the rendered gateway URL with
  the same headers

## Completion Validation

Run the completion gate after install and configuration:

```bash
bash skills/splunk-mcp-server-setup/scripts/validate.sh \
  --completion \
  --mcp-bearer-token-file /tmp/splunk_mcp.token
```

In addition to app version, visibility, configuration, REST endpoint, KV Store,
and ping checks, completion mode requires a successful authenticated MCP
`initialize`, verifies that `tools/list` exposes `splunk_get_info`, and safely
invokes `splunk_get_info` through `tools/call`. It also checks notification
semantics, rejects an untrusted-Origin probe, and enforces bounded token and
rate-limit settings. It uses the encrypted bearer-token file for MCP requests;
the Splunk admin session remains limited to configuration checks. Validation
also requires the enabled tools to exactly match a reviewed allowlist and
rejects paginated/incomplete inventories. With no `--allowed-tools-file`, the
minimal default allowlist is `["splunk_get_info"]`; pass a non-empty JSON array
through `--allowed-tools-file` when additional tools have been explicitly
reviewed. Validation requires HTTP 200 for the
shipped `dashboard`, `monitoring`, `tools`, and `tool_settings` views.

Release 1.3.1 logs complete tool arguments and SPL to `_internal`; evaluation
must therefore use synthetic, non-sensitive data. Never place literal secrets
in custom tool headers or bodies because the `mcp_tools` collection can expose
those definitions broadly. Enabled-tool policy, malformed JSON-RPC handling,
Host validation, response bounds, cache headers, CUI JWT verification, and
cluster-wide rate-limit behavior remain vendor-review items, not controls this
repository claims to validate.

Passing configuration-value checks does not override the package review
status or prove that vendor code consumes every documented setting. Production
approval remains blocked until a fixed package passes static and live review.
