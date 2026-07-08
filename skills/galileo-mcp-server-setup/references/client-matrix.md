# Galileo MCP Client Matrix

| Client | Rendered output | Runtime secret handling | Notes |
| --- | --- | --- | --- |
| Cursor | `mcp/cursor.mcp.json` | `${env:GALILEO_API_KEY}` | Direct HTTP MCP config. Officially documented by Galileo. |
| VS Code | `mcp/vscode.mcp.json` | `${input:galileo-api-key}` password prompt | Direct HTTP MCP config. Officially documented by Galileo. |
| Codex | `mcp/codex-register-galileo-mcp.sh` + bridge | `mcp/.env.galileo-mcp` local-only file | Uses the dependency-free Node.js stdio/Streamable HTTP bridge so the key is not placed in config or argv. |
| Claude Code | `mcp/claude.mcp.json` + bridge | `mcp/.env.galileo-mcp` local-only file | Rendered for Claude Code-style local MCP config. |
| AWS Kiro | `mcp/kiro.mcp.json` + bridge | `mcp/.env.galileo-mcp` local-only file | Uses the same local bridge pattern as Codex/Claude. |

## Bridge Pattern

The local bridge loads owner-only `.env.galileo-mcp` from the rendered `mcp/`
directory and sends Streamable HTTP directly with Node.js core modules. It
supports JSON and SSE responses, MCP session IDs, server notifications, and all
JSON-RPC methods while rejecting redirects. Initialize ordering is preserved,
then POSTs run concurrently for cancellation safety. Optional server SSE uses
per-event bounds and capped reconnect backoff. The bridge never places the API
key in process arguments or diagnostic output. Run `chmod 600` on the
populated env file and any referenced key file.

## Install Posture

This skill does not copy configs into user or workspace config files. It prints
the install commands in `mcp/README.md` and leaves review/application to the
operator.

## CLI Aliases

`--client all` renders the full matrix. `claude-code`, `vs-code`, and
`aws-kiro` normalize to `claude`, `vscode`, and `kiro`.
