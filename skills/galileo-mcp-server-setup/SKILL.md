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
console URL unless the user provides a specific `--mcp-url`.

## Supported Paths

1. **Client setup**: render Cursor, VS Code, Codex, Claude Code, and AWS Kiro
   configs for `https://api.galileo.ai/mcp/http/mcp` or a self-hosted Galileo
   deployment.
2. **Secret-safe bridges**: use environment placeholders or local
   `.env.galileo-mcp` bridge files; never inline Galileo API keys.
3. **Tool inventory**: probe `initialize`, `tools/list`, `prompts/list`, and
   `resources/list` without credentials, then compare live tool names and
   schemas with the checked-in catalog.
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

`setup.sh` supports `--render`, `--validate`, `--doctor`, `--probe`,
`--dry-run`, `--json`, `--client`, `--spec`, `--output-dir`, `--mcp-url`,
`--galileo-console-url`, `--galileo-api-key-file`,
`--accept-galileo-mcp-write-tools`, and `--allow-loose-key-perms`.
Client aliases include `all`, `claude-code`, `vs-code`, and `aws-kiro`.

There is no `--apply` mode in v1. Rendered files explain the install commands,
but the setup script never copies files into real client config paths.

## Secret Handling

Use file-based or client-side secret injection only:

- `--galileo-api-key-file` for optional validation/probe checks
- `${env:GALILEO_API_KEY}` for Cursor and local bridge workflows
- `${input:galileo-api-key}` for VS Code prompt-string workflows
- `.env.galileo-mcp` local-only bridge file for Codex, Claude Code, and Kiro

Never pass API keys in chat or argv. Direct secret flags such as
`--galileo-api-key`, `--api-key`, `--token`, `--password`, and
`--authorization` are rejected.

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
