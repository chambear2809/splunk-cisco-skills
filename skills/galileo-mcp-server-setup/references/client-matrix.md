# Galileo MCP Client Matrix

| Client | Rendered output | Runtime secret handling | Notes |
| --- | --- | --- | --- |
| Cursor | `mcp/cursor.mcp.json` | `${env:GALILEO_API_KEY}` | Direct HTTP MCP config. Officially documented by Galileo. |
| VS Code | `mcp/vscode.mcp.json` | `${input:galileo-api-key}` password prompt | Direct HTTP MCP config. Officially documented by Galileo. |
| Codex | `mcp/codex-register-galileo-mcp.sh` + bridge | `mcp/.env.galileo-mcp` local-only file | Uses local `mcp-remote` bridge so the key is not placed in config. |
| Claude Code | `mcp/claude.mcp.json` + bridge | `mcp/.env.galileo-mcp` local-only file | Rendered for Claude Code-style local MCP config. |
| AWS Kiro | `mcp/kiro.mcp.json` + bridge | `mcp/.env.galileo-mcp` local-only file | Uses the same local bridge pattern as Codex/Claude. |

## Bridge Pattern

The local bridge loads `.env.galileo-mcp` from the rendered `mcp/` directory and
then starts `mcp-remote`. Header arguments use literal placeholders, for
example `Galileo-API-Key: ${GALILEO_API_KEY}`, so the wrapper does not expand
the secret into its own process arguments.

## Install Posture

This skill does not copy configs into user or workspace config files. It prints
the install commands in `mcp/README.md` and leaves review/application to the
operator.

## CLI Aliases

`--client all` renders the full matrix. `claude-code`, `vs-code`, and
`aws-kiro` normalize to `claude`, `vscode`, and `kiro`.
