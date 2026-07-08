---
name: galileo-mcp-server-setup
description: >-
  Render, validate, probe, and document safe client setup for the official
  Galileo MCP Server (`https://api.galileo.ai/mcp/http/mcp`) across Cursor,
  VS Code, Codex, Claude Code, and AWS Kiro. Use when configuring Galileo MCP,
  registering Galileo with IDE/agent clients, inventorying live MCP tools, or
  auditing Galileo MCP product coverage. Covers Galileo API-key secret handling,
  self-hosted URL derivation, live MCP tool inventory and drift checks,
  write/generation tool gating, MCP tool-call observability handoffs, and
  explicit boundaries between Galileo MCP IDE workflows and broader Galileo
  platform, Agent Control, Splunk HEC/OTLP, dashboard, and detector automation.
compatibility: "No direct Splunk Platform runtime dependency. This workflow can be used alongside Splunk Cloud Platform 10.5.2605 through its documented external APIs or handoffs."
metadata:
  splunk_cloud_10_5: "not-applicable"
  compatibility_verified: "2026-07-02"
---

# Galileo MCP Server Setup

This skill is the repo-owned workflow for the official Galileo MCP Server. It
is render-first and client-tooling focused: it prepares MCP client
configuration, validates that no secrets were written, inventories the live MCP
tool surface, and points broader Galileo/Splunk work to the existing skills.

## Required Intake

Before rendering, validating, doctoring, probing, or auditing this skill, ask
the user for the Galileo instance console URL and record the exact value they
provide, for example `https://console.demo-v2.galileocloud.io/`. Do not assume
`https://api.galileo.ai/mcp/http/mcp` unless the user explicitly confirms the
default Galileo Cloud instance.

Pass the URL as `--galileo-console-url "$GALILEO_CONSOLE_URL"` or set
`galileo.console_url` in the spec. The renderer derives the MCP URL from that
console URL unless the user provides a specific `--mcp-url`. HTTPS is required
for every non-loopback console and MCP endpoint; cleartext HTTP is accepted
only for `localhost`, `*.localhost`, or loopback IP validation fixtures.

## Supported Paths

1. **Client setup**: render Cursor, VS Code, Codex, Claude Code, and AWS Kiro
   configs for `https://api.galileo.ai/mcp/http/mcp` or a self-hosted Galileo
   deployment.
2. **Secret-safe bridges**: use environment placeholders or owner-only local
   `.env.galileo-mcp` bridge files; never inline Galileo API keys. The rendered
   dependency-free Node.js bridge translates stdio JSON-RPC to Streamable HTTP
   directly; it does not rely on `mcp-remote`.
3. **Tool inventory**: probe `initialize`, `tools/list`, `prompts/list`, and
   `resources/list` without credentials, then compare live server identity,
   version, tool names, and schemas with the checked-in catalog.
4. **Risk gating**: treat dataset and prompt creation tools as
   write/generation tools that require explicit operator review.
5. **Observability handoff**: render a Python MCP client + `add_tool_span`
   handoff for applications that call MCP servers and need Galileo tool-span
   logging.
6. **Product boundaries**:
   - Full Galileo lifecycle and Splunk wiring: `galileo-platform-setup`
   - Agent Control and Cursor hook governance: `galileo-agent-control-setup`
   - Splunk HEC/OTLP, dashboards, and detectors: existing Splunk skills
   - Dataset versioning/collaboration, experiment groups/ranking, metric
     recomputation, SQL/Text-to-SQL metrics, Agent Graph analytics, saved
     views, Protect, Luna/Luna Studio, Trends, annotations, feedback,
     Python/TypeScript SDK reference work, provider/cost management, and any
     other Galileo capability outside the live MCP tool catalog: explicit
     handoff, not silent omission

### July 7, 2026 product boundaries

The July 7 release adds platform capabilities, not new tools in the observed
9-tool MCP catalog. Keep these explicit when planning MCP client setup:

- AI Assistant is an enterprise beta console feature that requires a configured
  LLM integration and support enablement. It is currently read-only and has no
  documented public Assistant API or MCP tool. Hand off readiness, enablement,
  and console evidence to `galileo-platform-setup`.
- Global dashboards span projects and log streams in the console. The documented
  public Trends API remains project/log-stream scoped, so do not claim global
  dashboard CRUD automation; hand off UI readiness and evidence.
- Generic alert webhooks support None, Bearer, or Basic authentication and a
  version 1.0 payload, but no public webhook/alert CRUD API or MCP tool is
  documented. Hand off receiver or relay design, configuration, and validation.
- Experiment groups require Galileo Python SDK 2.2.0 or later. The MCP
  `setup_galileo_experiment` tool provides guidance only; group lifecycle,
  comparison, and ranking remain a platform handoff.
- Large-dataset Playground and experiment metric processing now uses batching.
  Galileo does not document an exact maximum or client-side batch-size control;
  MCP dataset creation/status does not automate batched experiment execution.

## Safe First Command

```bash
bash skills/galileo-mcp-server-setup/scripts/setup.sh --help
```

## Primary Workflow

Render the full client matrix:

```bash
bash skills/galileo-mcp-server-setup/scripts/setup.sh \
  --render \
  --galileo-console-url "$GALILEO_CONSOLE_URL" \
  --client cursor,claude,codex,vscode,kiro \
  --output-dir galileo-mcp-rendered
```

Render from the non-secret intake template:

```bash
bash skills/galileo-mcp-server-setup/scripts/setup.sh \
  --render \
  --spec skills/galileo-mcp-server-setup/template.example \
  --output-dir galileo-mcp-rendered
```

Render from a self-hosted Galileo console URL:

```bash
bash skills/galileo-mcp-server-setup/scripts/setup.sh \
  --render \
  --galileo-console-url https://console.galileo.example.com \
  --output-dir galileo-mcp-rendered
```

Validate rendered files:

```bash
bash skills/galileo-mcp-server-setup/scripts/validate.sh \
  --output-dir galileo-mcp-rendered
```

Probe live MCP metadata without credentials:

```bash
python3 skills/galileo-mcp-server-setup/scripts/probe_mcp.py \
  --mcp-url https://api.galileo.ai/mcp/http/mcp
```

Optionally verify an API key with a read-only `/v2/current_user` check:

```bash
chmod 600 /tmp/galileo_api_key
python3 skills/galileo-mcp-server-setup/scripts/probe_mcp.py \
  --auth-check \
  --galileo-api-key-file /tmp/galileo_api_key
```

## CLI Contract

`setup.sh` supports `--render`, `--validate`, `--doctor`, `--probe`, `--apply`,
`--dry-run`, `--json`, `--client`, `--spec`, `--output-dir`, `--mcp-url`,
`--galileo-console-url`, `--galileo-api-key-file`,
`--accept-galileo-mcp-write-tools`, and `--allow-loose-key-perms`.
Client aliases include `all`, `claude-code`, `vs-code`, and `aws-kiro`.

`--apply --client codex` writes a local file-backed bridge environment and runs
the rendered Codex registration helper. Cursor, VS Code, Claude, and Kiro config
merges remain explicit reviewed handoffs and fail closed under automated apply.

## Secret Handling

Use file-based or client-side secret injection only:

- `--galileo-api-key-file` for optional validation/probe checks and Codex apply
- `${env:GALILEO_API_KEY}` for Cursor and local bridge workflows
- `${input:galileo-api-key}` for VS Code prompt-string workflows
- `.env.galileo-mcp` local-only bridge file for Codex, Claude Code, and Kiro

Run `chmod 600 mcp/.env.galileo-mcp` after copying the example. The bridge also
checks a referenced `GALILEO_API_KEY_FILE` for owner-only permissions. The
lab-only `GALILEO_MCP_ALLOW_LOOSE_KEY_PERMS=1` override is never rendered or
enabled automatically.

The bridge sends `Accept: application/json, text/event-stream`, captures and
propagates `Mcp-Session-Id`, sends the negotiated `MCP-Protocol-Version`, and
supports JSON and SSE responses for initialize, notifications, tools, prompts,
and resources. HTTP redirects are rejected so the Galileo API key cannot be
forwarded to another origin. The initialize/initialized exchange is ordered;
subsequent POSTs are concurrent so `notifications/cancelled` can bypass the
tool request it cancels. Server SSE is bounded per event and reconnects with
capped exponential backoff; a server that rejects GET disables that optional
stream without affecting POST calls.

Never pass API keys in chat or argv. Direct secret flags such as
`--galileo-api-key`, `--api-key`, `--token`, `--password`, and
`--authorization` are rejected.

The optional authenticated `/v2/current_user` probe rejects HTTP redirects and
returns only status plus response-key names. It never forwards the
`Galileo-API-Key` header to a redirect target or includes its value in errors.

## Tool Groups

- **Guidance/public**: `search_docs`, `integrate_galileo_with_openai`,
  `integrate_galileo_with_langchain`, `setup_galileo_experiment`
- **Tenant read**: `get_logstream_insights`, `get_logstream_signals`,
  `validate_dataset`
- **Tenant write/generation**: `create_galileo_dataset`,
  `create_prompt_template`

Unknown future tools are treated as manual-approval-only until the catalog is
updated.

## Validation

Run the complete audit gate:

```bash
bash skills/galileo-mcp-server-setup/scripts/deep_audit.sh
```

For deterministic local-only validation without live Galileo network checks:

```bash
bash skills/galileo-mcp-server-setup/scripts/deep_audit.sh --skip-live
```

Focused rendered-output validation:

```bash
bash skills/galileo-mcp-server-setup/scripts/validate.sh \
  --output-dir galileo-mcp-rendered
python3 -m py_compile \
  skills/galileo-mcp-server-setup/scripts/render_assets.py \
  skills/galileo-mcp-server-setup/scripts/probe_mcp.py \
  skills/galileo-mcp-server-setup/scripts/audit_product_coverage.py
```

See `reference.md` and the files under `references/` for the client matrix,
tool catalog, product gap matrix, and troubleshooting notes.
