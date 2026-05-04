"""Render MCP client configurations for the official ThousandEyes MCP Server.

The skill is render-first by default. Apply (writing into the user's actual
client config locations) is performed by setup.sh after the renderer has
produced the artifacts.

The renderer never reads token files. Configs use placeholders or runtime
prompt patterns so secrets are not written to disk.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SKILL_NAME = "cisco-thousandeyes-mcp-setup"
TE_MCP_URL = "https://api.thousandeyes.com/mcp"
TE_MCP_RATE_LIMIT_PER_MINUTE = 240

VALID_CLIENTS = {"cursor", "claude", "codex", "vscode", "kiro"}
VALID_AUTH = {"bearer", "oauth2"}

READ_ONLY_TOOLS = (
    "List Tests",
    "Get Test Details",
    "List Events",
    "Get Event Details",
    "List Alerts",
    "Get Alert Details",
    "Search Outages",
    "Get Anomalies",
    "Get Metrics",
    "Get Service Map",
    "Views Explanations",
    "List Endpoint Agents and Tests",
    "Get Endpoint Agent Metrics",
    "Get Connected Device",
    "Get Cloud and Enterprise Agents",
    "Get Path Visualization",
    "Get Full Path Visualization",
    "Get BGP Test Results",
    "Get BGP Route Details",
    "Get Account Groups",
    "Search Templates",
)
WRITE_TOOLS = (
    "Create Synthetic Test",
    "Update Synthetic Test",
    "Delete Synthetic Test",
    "Run Instant Test",
    "Deploy Template",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--clients",
        required=True,
        help="Comma-separated client list (cursor, claude, codex, vscode, kiro).",
    )
    parser.add_argument("--auth", choices=sorted(VALID_AUTH), default="bearer")
    parser.add_argument("--te-token-file", default="")
    parser.add_argument("--cursor-scope", choices=("user", "workspace"), default="user")
    parser.add_argument("--cursor-marketplace-link", default="true")
    parser.add_argument("--claude-connector-name", default="ThousandEyes MCP Server")
    parser.add_argument("--claude-auto-allow-read-only", default="true")
    parser.add_argument("--codex-server-name", default="thousandeyes")
    parser.add_argument("--codex-replace-existing", default="true")
    parser.add_argument("--vscode-use-input-prompt", default="true")
    parser.add_argument("--kiro-use-oauth2", default="false")
    parser.add_argument("--accept-write-tools", default="false")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def bool_flag(value: str) -> bool:
    return str(value).lower() == "true"


def selected_clients(raw: str) -> list[str]:
    seen: list[str] = []
    for token in raw.split(","):
        name = token.strip().lower()
        if not name:
            continue
        if name not in VALID_CLIENTS:
            raise SystemExit(
                f"ERROR: unknown client {name!r}. Valid: {sorted(VALID_CLIENTS)}"
            )
        if name not in seen:
            seen.append(name)
    if not seen:
        raise SystemExit("ERROR: --clients requires at least one client.")
    return seen


def write_text(path: Path, content: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(0o755)


def cursor_config(auth: str, marketplace_link: bool, token_file: str) -> str:
    """Render Cursor `.cursor/mcp.json` content.

    Cursor accepts an HTTP MCP server with custom Authorization headers via
    the documented `headers` block (per
    docs.thousandeyes.com/.../thousandeyes-mcp-server). For OAuth2, no
    headers are needed — the MCP client opens a browser to complete the
    OAuth2 flow.
    """
    if auth == "bearer":
        # Use the well-known TE_API_TOKEN env-var convention. The user must
        # export it in their shell or via the Cursor secrets UI; we never
        # inline the token value.
        body: dict[str, Any] = {
            "mcpServers": {
                "ThousandEyes": {
                    "url": TE_MCP_URL,
                    "headers": {"Authorization": "Bearer ${env:TE_API_TOKEN}"},
                }
            }
        }
    else:
        body = {"mcpServers": {"ThousandEyes": {"url": TE_MCP_URL}}}

    leading_comment = ""
    if marketplace_link:
        leading_comment = (
            "// Cisco ThousandEyes Cursor Marketplace plugin (turnkey alternative):\n"
            "//   https://cursor.com/marketplace/cisco-thousand-eyes\n"
            "//\n"
            "// Manual config (this file). For OAuth Bearer, export TE_API_TOKEN in\n"
            "// your shell or store it in Cursor's secrets UI; do NOT inline the\n"
            "// token here. Token-file path provided to the renderer (for reference\n"
            "// only; never read by the renderer):\n"
            f"//   {token_file or '(none)'}\n"
        )
    return leading_comment + json.dumps(body, indent=2, sort_keys=True) + "\n"


def claude_config(auth: str, connector_name: str, auto_allow_read_only: bool) -> str:
    """Render Claude Code `.mcp.json` content + connector flow doc.

    Claude Desktop and Claude (web, paid plans) both register MCP via
    Settings > Connectors > Add custom connector. Free Claude users can
    only register via the Desktop app.
    """
    body: dict[str, Any]
    if auth == "bearer":
        body = {
            "mcpServers": {
                connector_name: {
                    "url": TE_MCP_URL,
                    "headers": {"Authorization": "Bearer ${env:TE_API_TOKEN}"},
                }
            }
        }
    else:
        body = {"mcpServers": {connector_name: {"url": TE_MCP_URL}}}

    rendered = json.dumps(body, indent=2, sort_keys=True) + "\n"

    instructions = (
        "// Claude Code custom-connector flow:\n"
        "//   1. Open Claude > Settings > Connectors > Add custom connector.\n"
        f"//   2. Name = {connector_name!r}.\n"
        f"//   3. Remote MCP server URL = {TE_MCP_URL}.\n"
        "//   4. Sign in with ThousandEyes credentials and accept the DCR token share.\n"
    )
    if auto_allow_read_only:
        instructions += (
            "//   5. Click Configure for ThousandEyes MCP Server, turn on auto-allow\n"
            "//      for the Read-only tool group only.\n"
        )
    return instructions + rendered


def codex_register_script(server_name: str, replace_existing: bool, auth: str, token_file: str) -> str:
    """Render the Codex registration shell.

    Mirrors the structure of agent/register-codex-splunk-cisco-skills-mcp.sh
    so operators have a familiar shape. The script never echoes the token
    value. Bearer auto-registration is refused for Codex because mcp-remote
    requires a header argument that would expose the token on process argv.
    """
    replace_block = (
        'if codex mcp get "${SERVER_NAME}" --json >/dev/null 2>&1; then\n'
        '    codex mcp remove "${SERVER_NAME}" >/dev/null\n'
        "fi\n"
        if replace_existing
        else ""
    )

    if auth == "bearer":
        body = (
            f'TOKEN_FILE="{token_file or "${TE_TOKEN_FILE:-}"}"\n'
            f'if [[ -z "${{TOKEN_FILE}}" || ! -r "${{TOKEN_FILE}}" ]]; then\n'
            f'    echo "ERROR: TE token file not readable: ${{TOKEN_FILE}}" >&2\n'
            f'    exit 1\n'
            f'fi\n'
            f'echo "ERROR: Codex bearer auto-registration is disabled because mcp-remote --header would expose the token on process argv." >&2\n'
            f'echo "Re-render with --auth oauth2 for browser consent, or use a client-side secret store that does not put bearer tokens on argv." >&2\n'
            f'exit 2\n'
        )
    else:
        body = (
            f'# OAuth2 flow: a browser will open to complete consent on first run.\n'
            f'exec codex mcp add "${{SERVER_NAME}}" -- npx -y mcp-remote@latest \\\n'
            f'    "{TE_MCP_URL}" \\\n'
            f'    --transport http-only\n'
        )

    return (
        "#!/usr/bin/env bash\n"
        "# Register the official ThousandEyes MCP Server with Codex.\n"
        "# Generated by skills/cisco-thousandeyes-mcp-setup. Do not commit.\n"
        "set -euo pipefail\n"
        "\n"
        f'SERVER_NAME="${{1:-{server_name}}}"\n'
        "\n"
        "if ! command -v codex >/dev/null 2>&1; then\n"
        '    echo "ERROR: codex CLI not found on PATH." >&2\n'
        "    exit 1\n"
        "fi\n"
        "\n"
        "if ! command -v npx >/dev/null 2>&1; then\n"
        '    echo "ERROR: npx not found. Install Node.js: https://nodejs.org/en/download" >&2\n'
        "    exit 1\n"
        "fi\n"
        "\n"
        f"{replace_block}"
        "\n"
        f"{body}"
    )


def vscode_config(auth: str, use_input_prompt: bool) -> str:
    """Render VS Code MCP config.

    VS Code's Copilot MCP integration accepts an `inputs[]` block with
    `${input:te-key}` prompt-string variables — the value is entered at
    runtime and is never stored in settings.json or git.
    """
    if auth == "bearer":
        if use_input_prompt:
            body: dict[str, Any] = {
                "inputs": [
                    {
                        "type": "promptString",
                        "id": "te-key",
                        "description": "ThousandEyes API Key",
                        "password": True,
                    }
                ],
                "servers": {
                    "ThousandEyes": {
                        "url": TE_MCP_URL,
                        "headers": {"Authorization": "Bearer ${input:te-key}"},
                    }
                },
            }
        else:
            body = {
                "servers": {
                    "ThousandEyes": {
                        "url": TE_MCP_URL,
                        "headers": {"Authorization": "Bearer ${env:TE_API_TOKEN}"},
                    }
                }
            }
    else:
        body = {"servers": {"ThousandEyes": {"url": TE_MCP_URL}}}
    return json.dumps(body, indent=2, sort_keys=True) + "\n"


def kiro_config(auth: str, use_oauth2: bool) -> str:
    """Render AWS Kiro MCP config.

    Kiro uses `npx mcp-remote@latest` because it doesn't speak HTTP MCP
    natively — mcp-remote bridges. For Bearer auth, the AUTH_TOKEN env var
    flows through; for OAuth2, the browser flow runs on first invocation.
    """
    if use_oauth2 or auth == "oauth2":
        body: dict[str, Any] = {
            "mcpServers": {
                "ThousandEyes": {
                    "command": "npx",
                    "args": [
                        "mcp-remote@latest",
                        TE_MCP_URL,
                        "--transport",
                        "http-only",
                    ],
                }
            }
        }
    else:
        body = {
            "mcpServers": {
                "ThousandEyes": {
                    "command": "npx",
                    "args": [
                        "mcp-remote@latest",
                        TE_MCP_URL,
                        "--transport",
                        "http-only",
                        "--header",
                        "Authorization: Bearer ${AUTH_TOKEN}",
                    ],
                    "env": {"AUTH_TOKEN": "${env:TE_API_TOKEN}"},
                }
            }
        }
    return json.dumps(body, indent=2, sort_keys=True) + "\n"


def render_readme(args: argparse.Namespace, clients: list[str], accept_write_tools: bool) -> str:
    lines = [
        "# ThousandEyes MCP Server — rendered client configurations",
        "",
        f"Server URL: `{TE_MCP_URL}`",
        f"Auth flow:  `{args.auth}`",
        "",
        "## Rate limits",
        "",
        f"- OAuth Bearer Token usage shares the org-wide {TE_MCP_RATE_LIMIT_PER_MINUTE} req/min limit",
        "  with every other integration using a standard API token.",
        f"- Each OAuth2 client gets its own {TE_MCP_RATE_LIMIT_PER_MINUTE} req/min limit. Recommended",
        "  when multiple AI assistants share a TE org.",
        "- If you need a higher rate limit, contact ThousandEyes Support.",
        "",
        "## Read-only tool group (auto-allow recommended)",
        "",
    ]
    for tool in READ_ONLY_TOOLS:
        lines.append(f"- {tool}")
    lines.extend(
        [
            "",
            "## Write / Instant-Test tool group (default: NOT enabled)",
            "",
            "**WARNING.** `Run Instant Test` consumes ThousandEyes units identically",
            "to scheduled tests. `Create/Update/Delete Synthetic Test` mutates TE",
            "configuration. `Deploy Template` provisions multiple assets at once.",
            "",
            "Tools in this group:",
            "",
        ]
    )
    for tool in WRITE_TOOLS:
        lines.append(f"- {tool}")
    if accept_write_tools:
        lines.extend(
            [
                "",
                "`--accept-te-mcp-write-tools` was set. Clients that support",
                "per-tool gating render with the write group enabled. Review the",
                "per-client config and confirm before pointing the AI assistant",
                "at production.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "`--accept-te-mcp-write-tools` was NOT set. Configure per-tool",
                "approval in each client manually if you decide to enable any",
                "write tool after this initial review.",
            ]
        )
    lines.extend(["", "## Per-client install steps", ""])

    if "cursor" in clients:
        lines.extend(
            [
                "### Cursor",
                "",
                "- Manual config: copy `mcp/cursor.mcp.json` to either `~/.cursor/mcp.json`",
                "  (user scope) or `<repo>/.cursor/mcp.json` (workspace scope).",
                "- Marketplace plugin (turnkey alternative): https://cursor.com/marketplace/cisco-thousand-eyes",
                "- For OAuth Bearer, export `TE_API_TOKEN` in your shell rc file or store it",
                "  in Cursor's secrets UI. The rendered config never inlines the token.",
                "",
            ]
        )
    if "claude" in clients:
        lines.extend(
            [
                "### Claude Code",
                "",
                "- Open Claude > Settings > Connectors > Add custom connector.",
                f"- Name: `{args.claude_connector_name}`",
                f"- Remote MCP server URL: `{TE_MCP_URL}`",
                "- Sign in with ThousandEyes credentials and accept the DCR token share.",
                "- Configure auto-allow for the Read-only tools.",
                "- For free Claude accounts, custom connectors are Desktop-only; paid",
                "  plans support custom connectors via the web app.",
                "",
            ]
        )
    if "codex" in clients:
        if args.auth == "bearer":
            lines.extend(
                [
                    "### Codex",
                    "",
                    "- Bearer auto-registration is intentionally disabled because",
                    "  `mcp-remote --header` would expose the token on process argv.",
                    "- Re-render with `--auth oauth2` for browser consent.",
                    "",
                ]
            )
        else:
            lines.extend(
                [
                    "### Codex",
                    "",
                    "- Run `bash mcp/codex-register-te-mcp.sh` to register with Codex.",
                    "- Requires Node.js (`npx`) on PATH.",
                    "",
                ]
            )
    if "vscode" in clients:
        lines.extend(
            [
                "### VS Code (Copilot)",
                "",
                "- Copy `mcp/vscode.mcp.json` to your VS Code MCP servers config.",
                "- The `${input:te-key}` prompt asks for the API token at runtime.",
                "  Cancel and rerun if you mistype — the value is never written to disk.",
                "- Requires Node.js if your VS Code MCP runtime uses npx.",
                "",
            ]
        )
    if "kiro" in clients:
        lines.extend(
            [
                "### AWS Kiro",
                "",
                "- Copy `mcp/kiro.mcp.json` to `~/.kiro/settings/mcp.json`.",
                "- Requires Node.js (`npx`) on PATH for the `mcp-remote@latest` bridge.",
                "- For OAuth Bearer mode, set `TE_API_TOKEN` in your shell environment.",
                "",
            ]
        )
    return "\n".join(lines) + "\n"


def render_metadata(args: argparse.Namespace, clients: list[str], warnings: list[str]) -> str:
    payload = {
        "skill": SKILL_NAME,
        "te_mcp_url": TE_MCP_URL,
        "auth": args.auth,
        "clients": clients,
        "accept_write_tools": bool_flag(args.accept_write_tools),
        "warnings": warnings,
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def warnings(args: argparse.Namespace, clients: list[str]) -> list[str]:
    items: list[str] = []
    if args.auth == "bearer" and not args.te_token_file:
        items.append(
            "Bearer auth selected but --te-token-file not provided. The rendered configs "
            "use ${env:TE_API_TOKEN}; set this env var in the operator's shell."
        )
    if bool_flag(args.accept_write_tools):
        items.append(
            "Write/Instant-Test tool group enabled — Run Instant Test consumes TE units."
        )
    if "cursor" in clients and bool_flag(args.cursor_marketplace_link):
        items.append(
            "Cisco ThousandEyes Cursor Marketplace plugin is a turnkey alternative; "
            "consider it before deploying the manual config."
        )
    return items


def rendered_plan(args: argparse.Namespace, clients: list[str]) -> dict[str, Any]:
    return {
        "skill": SKILL_NAME,
        "output_dir": str(Path(args.output_dir).resolve()),
        "clients": clients,
        "auth": args.auth,
        "accept_write_tools": bool_flag(args.accept_write_tools),
        "warnings": warnings(args, clients),
        "rendered_files": [
            f"mcp/{name}.mcp.json" if name != "codex" else "mcp/codex-register-te-mcp.sh"
            for name in clients
        ]
        + ["mcp/README.md", "metadata.json"],
    }


def main() -> int:
    args = parse_args()
    clients = selected_clients(args.clients)
    output_dir = Path(args.output_dir)

    if args.dry_run:
        plan = rendered_plan(args, clients)
        if args.json:
            print(json.dumps(plan, indent=2, sort_keys=True))
        else:
            print("ThousandEyes MCP Server render plan")
            print(f"Output directory: {plan['output_dir']}")
            print(f"Clients: {', '.join(plan['clients'])}")
            print(f"Auth: {plan['auth']}")
            for warning in plan["warnings"]:
                print(f"WARN: {warning}")
            for path in plan["rendered_files"]:
                print(f"  render: {path}")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    mcp_dir = output_dir / "mcp"

    accept_write_tools = bool_flag(args.accept_write_tools)
    cursor_marketplace = bool_flag(args.cursor_marketplace_link)
    claude_auto_allow = bool_flag(args.claude_auto_allow_read_only)
    codex_replace = bool_flag(args.codex_replace_existing)
    vscode_use_input = bool_flag(args.vscode_use_input_prompt)
    kiro_oauth2 = bool_flag(args.kiro_use_oauth2)

    if "cursor" in clients:
        write_text(
            mcp_dir / "cursor.mcp.json",
            cursor_config(args.auth, cursor_marketplace, args.te_token_file),
        )
    if "claude" in clients:
        write_text(
            mcp_dir / "claude.mcp.json",
            claude_config(args.auth, args.claude_connector_name, claude_auto_allow),
        )
    if "codex" in clients:
        write_text(
            mcp_dir / "codex-register-te-mcp.sh",
            codex_register_script(
                args.codex_server_name, codex_replace, args.auth, args.te_token_file
            ),
            executable=True,
        )
    if "vscode" in clients:
        write_text(
            mcp_dir / "vscode.mcp.json",
            vscode_config(args.auth, vscode_use_input),
        )
    if "kiro" in clients:
        write_text(
            mcp_dir / "kiro.mcp.json",
            kiro_config(args.auth, kiro_oauth2),
        )

    write_text(mcp_dir / "README.md", render_readme(args, clients, accept_write_tools))
    write_text(output_dir / "metadata.json", render_metadata(args, clients, warnings(args, clients)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
