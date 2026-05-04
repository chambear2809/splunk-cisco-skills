# Per-client install matrix

| Client | Render output | Apply target | Token handling | OAuth Bearer | OAuth2 client |
|--------|---------------|--------------|----------------|--------------|---------------|
| Cursor | `mcp/cursor.mcp.json` | `~/.cursor/mcp.json` (user) or `<repo>/.cursor/mcp.json` (workspace) | `${env:TE_API_TOKEN}` from shell or Cursor secrets UI | yes | n/a (Cursor MCP HTTP supports headers, not OAuth2 flow directly) |
| Claude Code | `mcp/claude.mcp.json` (instructions only; actual registration is via Settings > Connectors) | Claude Settings > Connectors > Add custom connector | DCR token share via OAuth at registration | n/a (browser-mediated) | yes (paid plans on web; Desktop on free) |
| Codex | `mcp/codex-register-te-mcp.sh` | `codex mcp add ThousandEyes -- ...` | OAuth2 browser consent; Bearer helper refuses argv exposure | no auto-register | yes |
| VS Code | `mcp/vscode.mcp.json` | VS Code MCP servers config (varies by extension) | `${input:te-key}` runtime prompt (password type) | yes | yes |
| AWS Kiro | `mcp/kiro.mcp.json` | `~/.kiro/settings/mcp.json` | `${env:TE_API_TOKEN}` via `mcp-remote@latest --header` (Bearer) or browser flow (OAuth2) | yes | yes |

## Cursor — turnkey alternative

The Cisco ThousandEyes Cursor Marketplace plugin (https://cursor.com/marketplace/cisco-thousand-eyes) installs the MCP server with a single click and handles per-tool gating in the Cursor UI. Use it when:

- The operator is on Cursor and prefers a managed plugin to a manual config.
- The org wants the same install path on every developer machine.

Use the rendered `cursor.mcp.json` instead when:

- The operator wants workspace-scoped (per-repo) MCP registration.
- The org pins a specific configuration via the rendered file in source control (with the token still externalized).
- The marketplace plugin is unavailable or out of date relative to docs.

## Claude — custom connector flow

Free Claude users can only register MCP custom connectors via the Desktop app. Paid plans support adding connectors via the web app.

Steps (rendered into `mcp/claude.mcp.json` as comments):

1. Open Claude > Settings > Connectors > Add custom connector.
2. Set Name to the connector name from `template.example` (default `ThousandEyes MCP Server`).
3. Set Remote MCP server URL to `https://api.thousandeyes.com/mcp`.
4. Sign in with ThousandEyes credentials and accept the DCR token share.
5. Configure auto-allow for the Read-only tool group only. Leave the Write group requiring per-call approval.

## Codex — registration shell

The rendered `mcp/codex-register-te-mcp.sh` script:

1. Verifies `codex` is on PATH.
2. Verifies `npx` is on PATH (the `mcp-remote@latest` bridge requires Node.js).
3. Removes any existing Codex MCP registration with the same name (`replace_existing: true`).
4. Refuses Bearer auto-registration because `mcp-remote --header` would put the token on process argv.
5. For Codex, prefer OAuth2 browser consent or a client-side secret store that can inject the header without argv exposure.

Run with no arguments to use the default name from `template.example`, or pass a custom name as the first argument.

## VS Code — input prompt

The `${input:te-key}` pattern asks for the API key in a password-style prompt at MCP server start time. The token is held in the VS Code process memory only; it is never written to settings.json or git.

If the operator prefers an env var instead of the prompt, set `vscode.use_input_prompt: false` in the spec and export `TE_API_TOKEN` in the user shell profile.

## AWS Kiro — mcp-remote bridge

Kiro doesn't speak HTTP MCP natively — `mcp-remote@latest` (an npx-distributed Node.js bridge) is the canonical adapter recommended in the official TE MCP docs. For OAuth Bearer auth, the bridge picks up `AUTH_TOKEN` (mapped to `${env:TE_API_TOKEN}` in the rendered config) and sends it as the `Authorization` header. For OAuth2, the bridge opens a browser for consent.
