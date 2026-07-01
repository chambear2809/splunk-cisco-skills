"""Render safe client configuration for the official Galileo MCP Server."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse


SKILL_NAME = "galileo-mcp-server-setup"
DEFAULT_MCP_URL = "https://api.galileo.ai/mcp/http/mcp"
EXPECTED_SERVER_NAME = "EvalsInIDEServer"
EXPECTED_SERVER_VERSION = "1.27.1"

VALID_CLIENTS = {"cursor", "claude", "codex", "vscode", "kiro"}
DEFAULT_CLIENTS = ["cursor", "claude", "codex", "vscode", "kiro"]
CLIENT_ALIASES = {
    "all": DEFAULT_CLIENTS,
    "claude-code": ["claude"],
    "claudecode": ["claude"],
    "vs-code": ["vscode"],
    "vs_code": ["vscode"],
    "visual-studio-code": ["vscode"],
    "visualstudio-code": ["vscode"],
    "aws-kiro": ["kiro"],
}
DIRECT_SECRET_FLAGS = {
    "--access-token",
    "--api-key",
    "--api-token",
    "--authorization",
    "--bearer-token",
    "--galileo-api-key",
    "--password",
    "--token",
}

TOOL_CATALOG: list[dict[str, Any]] = [
    {
        "name": "integrate_galileo_with_langchain",
        "risk_group": "guidance_public",
        "required": ["language"],
        "properties": ["language"],
        "schema_sha256": "a6a782dc432bf60e09d42264f9533d86043e6e704d994bd9fe702d93b9c3c37c",
        "coverage": "LangChain and LangGraph observability guidance",
        "auto_allow": True,
    },
    {
        "name": "integrate_galileo_with_openai",
        "risk_group": "guidance_public",
        "required": ["language"],
        "properties": ["language"],
        "schema_sha256": "74131104916793729d7a6092b88a3766cade01f4668b16ba66e8981d8dbfd27f",
        "coverage": "OpenAI SDK wrapper guidance for Python and TypeScript",
        "auto_allow": True,
    },
    {
        "name": "get_logstream_insights",
        "risk_group": "tenant_read",
        "required": ["project", "log_stream"],
        "properties": ["project", "log_stream"],
        "schema_sha256": "aec39521ea02e18fa32d88dc9bb1dc9c7e720cb79087704b0c55362b915b23bc",
        "coverage": "Log stream insights and recommended improvements",
        "auto_allow": False,
    },
    {
        "name": "get_logstream_signals",
        "risk_group": "tenant_read",
        "required": ["project", "log_stream"],
        "properties": ["project", "log_stream"],
        "schema_sha256": "628178ceae9e2f9c884c6c46ab4d4a7980f9ff4151cca266e164b5285a03244d",
        "coverage": "Log stream signals; present live but missing from older example output",
        "auto_allow": False,
    },
    {
        "name": "validate_dataset",
        "risk_group": "tenant_read",
        "required": ["dataset_id"],
        "properties": ["dataset_id"],
        "schema_sha256": "eed688749cbb169a2090a90d3080e9a2b950251c1d0e7d21acab5a94aede7b0e",
        "coverage": "Synthetic dataset generation status and preview",
        "auto_allow": False,
    },
    {
        "name": "create_galileo_dataset",
        "risk_group": "tenant_write_generation",
        "required": ["description"],
        "properties": [
            "count",
            "csv_content",
            "data_source_type",
            "data_types",
            "description",
            "json_data",
            "model",
            "name",
            "project_id",
            "sample_data",
        ],
        "schema_sha256": "1e0c4f7e588e723ddae1c65d85f4785ec68986b40fc2ba4f219876d31e03c97f",
        "coverage": "Synthetic, CSV, or JSON dataset creation",
        "auto_allow": False,
    },
    {
        "name": "create_prompt_template",
        "risk_group": "tenant_write_generation",
        "required": ["name", "template"],
        "properties": [
            "frequency_penalty",
            "max_tokens",
            "model_alias",
            "name",
            "output_type",
            "presence_penalty",
            "project_id",
            "raw",
            "temperature",
            "template",
            "top_p",
        ],
        "schema_sha256": "5026768a9195f152f1d65a2a08d6f0ceac784bb14fd09b3a45e6dfbbe7e4f90f",
        "coverage": "Global prompt template creation",
        "auto_allow": False,
    },
    {
        "name": "setup_galileo_experiment",
        "risk_group": "guidance_public",
        "required": [],
        "properties": ["language"],
        "schema_sha256": "07dd26c2885f9bbaa49048a42d6188362b021f3931e4d15ca19424bd0fb32534",
        "coverage": "Experiment setup guidance",
        "auto_allow": True,
    },
    {
        "name": "search_docs",
        "risk_group": "guidance_public",
        "required": ["query"],
        "properties": ["query"],
        "schema_sha256": "9f109ec337868d70e1114f2dd32bda775e6bc09819e7bdfc3fedde07c64c2bd4",
        "coverage": "Galileo documentation search",
        "auto_allow": True,
    },
]

PRODUCT_GAP_MATRIX: list[dict[str, str]] = [
    {
        "area": "MCP client setup",
        "mcp_coverage": "first_class",
        "handoff": "galileo-mcp-server-setup",
    },
    {
        "area": "Tool inventory and drift",
        "mcp_coverage": "first_class_no_secret_probe",
        "handoff": "galileo-mcp-server-setup",
    },
    {
        "area": "Dataset creation/status",
        "mcp_coverage": "partial",
        "handoff": "galileo-platform-setup for complete dataset lifecycle",
    },
    {
        "area": "Dataset versioning, content update, download, sharing, and collaborators",
        "mcp_coverage": "not_mcp_server_setup",
        "handoff": "galileo-platform-setup for dataset lifecycle and access governance",
    },
    {
        "area": "Prompt template creation",
        "mcp_coverage": "partial",
        "handoff": "galileo-platform-setup for prompt manifests/versioning",
    },
    {
        "area": "Experiment setup",
        "mcp_coverage": "guidance_only",
        "handoff": "galileo-platform-setup for create/run assets",
    },
    {
        "area": "Experiment groups, comparison, ranking, playground runs, and unit-test gates",
        "mcp_coverage": "guidance_or_docs_search_only",
        "handoff": "galileo-platform-setup for experiment group and CI workflow handoffs",
    },
    {
        "area": "Projects, project sharing, users, groups, RBAC, SSO, and API keys",
        "mcp_coverage": "not_mcp_server_setup",
        "handoff": "galileo-platform-setup for enterprise/admin readiness",
    },
    {
        "area": "Log stream signals/insights",
        "mcp_coverage": "tenant_read",
        "handoff": "galileo-platform-setup for metrics/trends/export context",
    },
    {
        "area": "Observe traces, sessions, spans, exports, metrics, run insights, and alerts",
        "mcp_coverage": "not_mcp_server_setup",
        "handoff": "galileo-platform-setup for Observe runtime/export and Splunk wiring",
    },
    {
        "area": "Evaluate metrics, custom scorers, Luna-2, annotations, and feedback",
        "mcp_coverage": "not_mcp_server_setup",
        "handoff": "galileo-platform-setup for Evaluate/Luna/annotation handoffs",
    },
    {
        "area": "Luna Studio tutorials, metric training datasets, and scorer development workflows",
        "mcp_coverage": "docs_search_only",
        "handoff": "galileo-platform-setup for Luna/scorer workflow handoffs",
    },
    {
        "area": "Text-to-SQL metrics, preset metric benchmarks/examples, and metric recomputation",
        "mcp_coverage": "docs_search_only",
        "handoff": "galileo-platform-setup for metric/scorer readiness and recomputation handoffs",
    },
    {
        "area": "Agentic metrics, metric settings, scorer health scores, and Autotune",
        "mcp_coverage": "docs_search_only",
        "handoff": "galileo-platform-setup for metric/scorer readiness",
    },
    {
        "area": "Provider integrations, model aliases, model pricing, and costs",
        "mcp_coverage": "not_mcp_server_setup",
        "handoff": "galileo-platform-setup for provider/cost readiness",
    },
    {
        "area": "Trends dashboards, health scores, and organization jobs",
        "mcp_coverage": "not_mcp_server_setup",
        "handoff": "galileo-platform-setup for Trends/run-insights/admin handoffs",
    },
    {
        "area": "Agent Graph traffic analytics, aggregate graph, search, and metric overlays",
        "mcp_coverage": "not_mcp_server_setup",
        "handoff": "galileo-platform-setup for Agent Graph and console-debugging handoffs",
    },
    {
        "area": "Log stream and experiment saved views, table columns, and shared/private filters",
        "mcp_coverage": "not_mcp_server_setup",
        "handoff": "galileo-platform-setup for console-view and analysis handoffs",
    },
    {
        "area": "Protect stages, rulesets, notifications, and invoke runtime",
        "mcp_coverage": "not_mcp_server_setup",
        "handoff": "galileo-platform-setup for Protect runtime/assets",
    },
    {
        "area": "OpenAI/LangChain integration",
        "mcp_coverage": "guidance",
        "handoff": "galileo-platform-setup for runtime snippets and Splunk handoffs",
    },
    {
        "area": "Other framework integrations",
        "mcp_coverage": "docs_search_only",
        "handoff": "galileo-platform-setup for OpenTelemetry/OpenInference handoffs",
    },
    {
        "area": "Python/TypeScript SDK reference, wrappers, decorators, async logging, and release compatibility",
        "mcp_coverage": "docs_search_only",
        "handoff": "galileo-platform-setup for SDK parity and runtime-snippet handoffs",
    },
    {
        "area": "Multimodal logging, distributed tracing, tags, and metadata",
        "mcp_coverage": "docs_search_only",
        "handoff": "galileo-platform-setup for runtime logging handoffs",
    },
    {
        "area": "Cookbooks, sample projects, playgrounds, unit tests, and CI experiment gates",
        "mcp_coverage": "docs_search_only",
        "handoff": "galileo-platform-setup for sample/CI workflow handoffs",
    },
    {
        "area": "MCP tool-call logging",
        "mcp_coverage": "rendered_handoff",
        "handoff": "galileo-platform-setup for full runtime/Splunk wiring",
    },
    {
        "area": "Agent Control / Cursor hooks",
        "mcp_coverage": "not_mcp_server_setup",
        "handoff": "galileo-agent-control-setup",
    },
    {
        "area": "Splunk HEC/OTLP/O11y dashboards/detectors",
        "mcp_coverage": "not_mcp_server_setup",
        "handoff": "Splunk HEC, OTLP, OTel Collector, dashboard, and detector skills",
    },
    {
        "area": "Enterprise retention, TTL, privacy, custom deployments, and release checks",
        "mcp_coverage": "not_mcp_server_setup",
        "handoff": "galileo-platform-setup for enterprise/custom deployment readiness",
    },
]


def reject_direct_secret_flags(argv: list[str]) -> None:
    for arg in argv:
        flag = arg.split("=", 1)[0] if arg.startswith("--") else arg
        if flag in DIRECT_SECRET_FLAGS:
            print(
                f"ERROR: Direct secret flag {flag} is blocked. Use --galileo-api-key-file.",
                file=sys.stderr,
            )
            raise SystemExit(2)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    reject_direct_secret_flags(raw_args)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--spec", default="")
    parser.add_argument(
        "--clients",
        "--client",
        default="",
        help=(
            "Comma-separated client list: cursor, claude, codex, vscode, kiro. "
            "Aliases: all, claude-code, vs-code, aws-kiro."
        ),
    )
    parser.add_argument("--mcp-url", default="")
    parser.add_argument("--galileo-console-url", default="")
    parser.add_argument("--galileo-api-key-file", default="")
    parser.add_argument("--accept-write-tools", default="false")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(raw_args)


def bool_flag(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def bool_config(value: Any, default: bool = False) -> bool:
    if value in ("", None):
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def selected_clients(raw: Any) -> list[str]:
    result: list[str] = []
    if raw in ("", None):
        raw_tokens: list[Any] = list(DEFAULT_CLIENTS)
    elif isinstance(raw, list):
        raw_tokens = raw
    else:
        raw_tokens = str(raw).split(",")
    for token in raw_tokens:
        name = token.strip().lower()
        if not name:
            continue
        expanded = CLIENT_ALIASES.get(name, [name])
        for client_name in expanded:
            if client_name not in VALID_CLIENTS:
                raise SystemExit(
                    "ERROR: unknown client "
                    f"{name!r}. Valid: {', '.join(sorted(VALID_CLIENTS))}; "
                    f"aliases: {', '.join(sorted(CLIENT_ALIASES))}"
                )
            if client_name not in result:
                result.append(client_name)
    if not result:
        raise SystemExit("ERROR: at least one client is required.")
    return result


def parse_simple_yaml(text: str) -> dict[str, Any] | None:
    root: dict[str, Any] = {}
    stack: list[tuple[int, Any, Any | None, str | None]] = [(-1, root, None, None)]
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            return None
        current = stack[-1][1]
        parent = stack[-1][2]
        parent_key = stack[-1][3]
        if stripped.startswith("- "):
            if not isinstance(current, list):
                if not isinstance(parent, dict) or parent_key is None:
                    return None
                current = []
                parent[parent_key] = current
                stack[-1] = (stack[-1][0], current, parent, parent_key)
            current.append(coerce_yaml_scalar(stripped[2:].strip()))
            continue
        if ":" not in stripped or not isinstance(current, dict):
            return None
        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if value == "":
            child: dict[str, Any] = {}
            current[key] = child
            stack.append((indent, child, current, key))
            continue
        current[key] = coerce_yaml_scalar(value)
    return root


def coerce_yaml_scalar(value: str) -> Any:
    if value.startswith(("'", '"')) and value.endswith(("'", '"')) and len(value) >= 2:
        return value[1:-1]
    lower = value.lower()
    if lower in {"true", "false"}:
        return lower == "true"
    if lower in {"null", "none", "~"}:
        return None
    return value


def reject_inline_secrets(node: Any, path: str = "") -> None:
    secret_keys = {
        "access_token",
        "api_key",
        "api_token",
        "authorization",
        "bearer_token",
        "galileo_api_key",
        "password",
        "secret",
        "token",
    }
    if isinstance(node, dict):
        for key, value in node.items():
            normalized = re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")
            sub_path = f"{path}.{key}" if path else str(key)
            if normalized in secret_keys and isinstance(value, str) and value:
                if not value.startswith("${") and "PLACEHOLDER" not in value.upper():
                    raise SystemExit(
                        f"ERROR: Spec contains inline secret-like value at {sub_path}; "
                        "use file-based secret flags."
                    )
            reject_inline_secrets(value, sub_path)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            reject_inline_secrets(item, f"{path}[{index}]")


def load_spec(path: str) -> dict[str, Any]:
    if not path:
        return {}
    spec_path = Path(path)
    text = spec_path.read_text(encoding="utf-8")
    if spec_path.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        try:
            import yaml  # type: ignore[import-not-found]
        except ModuleNotFoundError as exc:
            data = parse_simple_yaml(text)
            if data is None:
                raise SystemExit(
                    "ERROR: YAML specs require PyYAML for complex syntax. Install "
                    "requirements-agent.txt or pass JSON."
                ) from exc
        else:
            data = yaml.safe_load(text)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise SystemExit(f"ERROR: Spec must be a mapping: {path}")
    if data.get("api_version") not in {None, f"{SKILL_NAME}/v1"}:
        raise SystemExit(
            f"ERROR: Spec api_version must be {SKILL_NAME}/v1; got {data.get('api_version')!r}"
        )
    reject_inline_secrets(data)
    return data


def get_nested(spec: dict[str, Any], dotted: str, default: Any) -> Any:
    current: Any = spec
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def build_config(args: argparse.Namespace, spec: dict[str, Any]) -> dict[str, Any]:
    clients_raw = args.clients if args.clients else get_nested(spec, "clients", DEFAULT_CLIENTS)
    mcp_url = args.mcp_url or str(get_nested(spec, "galileo.mcp_url", "") or "")
    console_url = args.galileo_console_url or str(get_nested(spec, "galileo.console_url", "") or "")
    accept_write = bool_flag(args.accept_write_tools) or bool_config(
        get_nested(spec, "accept_galileo_mcp_write_tools", False)
    )
    server_names = {
        client: str(get_nested(spec, f"client_options.{client}.server_name", "galileo") or "galileo")
        for client in VALID_CLIENTS
    }
    cursor_server = str(
        get_nested(spec, "client_options.cursor.server_name", "galileo_mcp_server")
        or "galileo_mcp_server"
    )
    vscode_server = str(
        get_nested(spec, "client_options.vscode.server_name", "galileo_mcp_server")
        or "galileo_mcp_server"
    )
    server_names["cursor"] = cursor_server
    server_names["vscode"] = vscode_server
    return {
        "clients": selected_clients(clients_raw),
        "mcp_url": derive_mcp_url(mcp_url, console_url),
        "galileo_console_url": console_url,
        "accept_write_tools": accept_write,
        "server_names": server_names,
        "galileo_api_key_file": args.galileo_api_key_file,
    }


def derive_mcp_url(mcp_url: str, console_url: str) -> str:
    if mcp_url.strip():
        return mcp_url.strip().rstrip("/")
    if not console_url.strip():
        return DEFAULT_MCP_URL
    raw = console_url.strip()
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw):
        raw = "https://" + raw
    parsed = urlparse(raw)
    host = parsed.netloc or parsed.path.split("/", 1)[0]
    if "console" in host:
        host = host.replace("console", "api", 1)
    elif not host.startswith("api."):
        host = "api." + host
    return urlunparse((parsed.scheme or "https", host, "/mcp/http/mcp", "", "", ""))


def write_text(path: Path, content: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(0o755)


def json_text(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def tool_catalog_payload() -> dict[str, Any]:
    return {
        "skill": SKILL_NAME,
        "source": DEFAULT_MCP_URL,
        "observed_server": {
            "name": EXPECTED_SERVER_NAME,
            "version": EXPECTED_SERVER_VERSION,
        },
        "tool_count": len(TOOL_CATALOG),
        "tools": TOOL_CATALOG,
        "prompts_expected": [],
        "resources_expected": [],
    }


def bridge_env_example(mcp_url: str) -> str:
    return (
        "# Copy to .env.galileo-mcp and keep the populated file local only.\n"
        f"GALILEO_MCP_URL={mcp_url}\n"
        "GALILEO_API_KEY=''\n"
        "# Optional for custom/self-hosted TLS labs only.\n"
        "# GALILEO_MCP_INSECURE_TLS=1\n"
    )


def cursor_config(mcp_url: str, server_name: str) -> str:
    payload = {
        "mcpServers": {
            server_name: {
                "url": mcp_url,
                "headers": {
                    "Galileo-API-Key": "${env:GALILEO_API_KEY}",
                    "Accept": "text/event-stream",
                },
            }
        }
    }
    return json_text(payload)


def vscode_config(mcp_url: str, server_name: str) -> str:
    payload = {
        "inputs": [
            {
                "type": "promptString",
                "id": "galileo-api-key",
                "description": "Galileo API Key",
                "password": True,
            }
        ],
        "servers": {
            server_name: {
                "url": mcp_url,
                "headers": {
                    "Galileo-API-Key": "${input:galileo-api-key}",
                    "Accept": "text/event-stream",
                },
            }
        },
    }
    return json_text(payload)


def stdio_config(server_name: str, bridge_js: Path) -> str:
    payload = {
        "mcpServers": {
            server_name: {
                "type": "stdio",
                "command": "node",
                "args": [str(bridge_js.resolve())],
            }
        }
    }
    return json_text(payload)


def codex_register_script(bridge_js: Path, default_server_name: str) -> str:
    bridge = str(bridge_js.resolve())
    return f"""#!/usr/bin/env bash
set -euo pipefail

SERVER_NAME="${{1:-{default_server_name}}}"
BRIDGE_JS="{bridge}"

if ! command -v codex >/dev/null 2>&1; then
    echo "ERROR: codex CLI not found on PATH." >&2
    exit 1
fi

if [[ ! -f "${{BRIDGE_JS}}" ]]; then
    echo "ERROR: Galileo MCP bridge not found: ${{BRIDGE_JS}}" >&2
    exit 1
fi

if codex mcp get "${{SERVER_NAME}}" --json >/dev/null 2>&1; then
    codex mcp remove "${{SERVER_NAME}}" >/dev/null
fi

exec codex mcp add "${{SERVER_NAME}}" -- node "${{BRIDGE_JS}}"
"""


def bridge_shell_script() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env.galileo-mcp"

if [[ -f "${ENV_FILE}" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "${ENV_FILE}"
    set +a
fi

if [[ -z "${GALILEO_MCP_URL:-}" ]]; then
    echo "galileo-mcp: set GALILEO_MCP_URL in ${ENV_FILE}" >&2
    exit 1
fi

if [[ -z "${GALILEO_API_KEY:-}" ]]; then
    echo "galileo-mcp: set GALILEO_API_KEY in ${ENV_FILE}" >&2
    exit 1
fi

if [[ "${GALILEO_MCP_INSECURE_TLS:-}" == "1" ]]; then
    export NODE_TLS_REJECT_UNAUTHORIZED=0
fi

if command -v mcp-remote >/dev/null 2>&1; then
    MCP_REMOTE=(mcp-remote)
elif command -v npx >/dev/null 2>&1; then
    MCP_REMOTE=(npx mcp-remote)
else
    echo "galileo-mcp: install mcp-remote or Node.js/npx" >&2
    exit 1
fi

# shellcheck disable=SC2016 # mcp-remote expands ${GALILEO_API_KEY} from env.
exec "${MCP_REMOTE[@]}" "${GALILEO_MCP_URL}" \\
    --transport http-only \\
    --header 'Galileo-API-Key: ${GALILEO_API_KEY}' \\
    --header 'Accept: text/event-stream'
"""


def bridge_js_script() -> str:
    return r'''#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { execFileSync, spawn } = require("child_process");

const scriptDir = __dirname;
const envFile = path.join(scriptDir, ".env.galileo-mcp");

function parseShellWord(value) {
  let result = "";
  let state = "normal";
  for (let i = 0; i < value.length; i++) {
    const ch = value[i];
    if (state === "single") {
      if (ch === "'") state = "normal";
      else result += ch;
      continue;
    }
    if (state === "double") {
      if (ch === '"') state = "normal";
      else if (ch === "\\") {
        i += 1;
        if (i < value.length) result += value[i];
      } else result += ch;
      continue;
    }
    if (ch === "'") state = "single";
    else if (ch === '"') state = "double";
    else if (ch === "\\") {
      i += 1;
      if (i < value.length) result += value[i];
    } else result += ch;
  }
  return result;
}

function loadEnvFile(filePath) {
  if (!fs.existsSync(filePath)) return;
  const lines = fs.readFileSync(filePath, "utf8").split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq === -1) continue;
    const key = trimmed.slice(0, eq).trim();
    const val = parseShellWord(trimmed.slice(eq + 1).trim());
    if (!(key in process.env)) process.env[key] = val;
  }
}

loadEnvFile(envFile);

function fail(message) {
  process.stderr.write("galileo-mcp: " + message + "\n");
  process.exit(1);
}

if (!process.env.GALILEO_MCP_URL) {
  fail("set GALILEO_MCP_URL in " + envFile);
}
if (!process.env.GALILEO_API_KEY) {
  fail("set GALILEO_API_KEY in " + envFile);
}
if (process.env.GALILEO_MCP_INSECURE_TLS === "1") {
  process.env.NODE_TLS_REJECT_UNAUTHORIZED = "0";
}

function findMcpRemote() {
  try {
    const result = execFileSync(
      process.platform === "win32" ? "where" : "which",
      ["mcp-remote"],
      { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }
    ).trim().split(/\r?\n/)[0].trim();
    if (result) return { cmd: result, args: [] };
  } catch (_) {
    // Fall back to npx.
  }
  return { cmd: process.platform === "win32" ? "npx.cmd" : "npx", args: ["mcp-remote"] };
}

const remote = findMcpRemote();
const args = [
  ...remote.args,
  process.env.GALILEO_MCP_URL,
  "--transport",
  "http-only",
  "--header",
  "Galileo-API-Key: ${GALILEO_API_KEY}",
  "--header",
  "Accept: text/event-stream",
];

const child = spawn(remote.cmd, args, { stdio: "inherit" });
child.on("error", function(err) {
  process.stderr.write("galileo-mcp: failed to start mcp-remote: " + err.message + "\n");
  process.exit(1);
});
child.on("exit", function(code, signal) {
  if (signal) process.kill(process.pid, signal);
  else process.exit(code !== null ? code : 0);
});
'''


def render_readme(clients: list[str], mcp_url: str, accept_write_tools: bool) -> str:
    guidance = [tool["name"] for tool in TOOL_CATALOG if tool["risk_group"] == "guidance_public"]
    tenant_read = [tool["name"] for tool in TOOL_CATALOG if tool["risk_group"] == "tenant_read"]
    tenant_write = [
        tool["name"] for tool in TOOL_CATALOG if tool["risk_group"] == "tenant_write_generation"
    ]
    lines = [
        "# Galileo MCP Server - rendered client configurations",
        "",
        f"Server URL: `{mcp_url}`",
        f"Selected clients: `{', '.join(clients)}`",
        "",
        "## Safety posture",
        "",
        "- These files are render-first handoffs; no client config was applied.",
        "- Do not commit `.env.galileo-mcp` or any populated API-key file.",
        "- Unknown future MCP tools should stay manual-approval-only until reviewed.",
        "",
        "## Tool groups",
        "",
        "Guidance/public tools:",
        "",
        *[f"- `{name}`" for name in guidance],
        "",
        "Tenant read tools:",
        "",
        *[f"- `{name}`" for name in tenant_read],
        "",
        "Tenant write/generation tools:",
        "",
        *[f"- `{name}`" for name in tenant_write],
        "",
    ]
    if accept_write_tools:
        lines.extend(
            [
                "`--accept-galileo-mcp-write-tools` was set. Keep per-call review on",
                "unless the operator has intentionally allowed dataset and prompt creation.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "`--accept-galileo-mcp-write-tools` was not set. Leave dataset and",
                "prompt creation tools behind manual approval.",
                "",
            ]
        )
    lines.extend(["## Install steps", ""])
    if "cursor" in clients:
        lines.extend(
            [
                "### Cursor",
                "",
                "- Copy `mcp/cursor.mcp.json` to `~/.cursor/mcp.json` or a workspace",
                "  `.cursor/mcp.json` after review.",
                "- Export `GALILEO_API_KEY` in the shell Cursor inherits, or use Cursor's",
                "  secret handling for the `${env:GALILEO_API_KEY}` placeholder.",
                "",
            ]
        )
    if "vscode" in clients:
        lines.extend(
            [
                "### VS Code",
                "",
                "- Copy `mcp/vscode.mcp.json` into VS Code's MCP user configuration.",
                "- VS Code prompts for `${input:galileo-api-key}` at runtime.",
                "",
            ]
        )
    if "codex" in clients:
        lines.extend(
            [
                "### Codex",
                "",
                "- Copy `mcp/.env.galileo-mcp.example` to `mcp/.env.galileo-mcp` and",
                "  set `GALILEO_API_KEY` locally.",
                "- Run `bash mcp/codex-register-galileo-mcp.sh`.",
                "",
            ]
        )
    if "claude" in clients:
        lines.extend(
            [
                "### Claude Code",
                "",
                "- Copy `mcp/.env.galileo-mcp.example` to `mcp/.env.galileo-mcp` and",
                "  set `GALILEO_API_KEY` locally.",
                "- Merge `mcp/claude.mcp.json` into the Claude Code MCP config.",
                "",
            ]
        )
    if "kiro" in clients:
        lines.extend(
            [
                "### AWS Kiro",
                "",
                "- Copy `mcp/.env.galileo-mcp.example` to `mcp/.env.galileo-mcp` and",
                "  set `GALILEO_API_KEY` locally.",
                "- Merge `mcp/kiro.mcp.json` into Kiro MCP settings.",
                "",
            ]
        )
    lines.extend(
        [
            "## Coverage files",
            "",
            "- `coverage/tool-catalog.json` records expected tool names, risk",
            "  groups, required args, property keys, and schema fingerprints.",
            "- `coverage/product-gap-matrix.json` records Galileo product areas",
            "  covered by MCP versus explicit handoffs.",
            "",
            "## Deep audit",
            "",
            "Before installing client configs, run from the repo root:",
            "",
            "```bash",
            "bash skills/galileo-mcp-server-setup/scripts/deep_audit.sh",
            "```",
            "",
            "## Verification prompts",
            "",
            "- `Can you show me how to add Galileo logging to my agent bot?`",
            "- `Help me create a synthetic dataset for customer support queries.`",
            "- `How do I integrate Galileo with LangChain?`",
            "",
            "## Handoffs",
            "",
            "- Full Galileo lifecycle and Splunk wiring: `galileo-platform-setup`",
            "- Agent Control and Cursor hook governance: `galileo-agent-control-setup`",
            "- Splunk HEC/OTLP/O11y dashboards/detectors: existing Splunk skills",
            "",
        ]
    )
    return "\n".join(lines)


def render_observability_handoff(mcp_url: str) -> str:
    return f"""# Galileo MCP Tool-Span Logging Handoff

Use this when an application calls MCP servers and needs those tool calls logged
as Galileo tool spans. This mirrors the official Galileo MCP logging sample.

## Environment

```ini
GALILEO_API_KEY=''  # set in env or a secret manager
GALILEO_PROJECT=<project-name>
GALILEO_LOG_STREAM=<log-stream-name>
MCP_SERVER_URL={mcp_url}
```

## Python Pattern

```python
import os
from contextlib import AsyncExitStack
from datetime import datetime
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from galileo import galileo_context

async def connect_mcp():
    stack = AsyncExitStack()
    read, write, _ = await stack.enter_async_context(
        streamablehttp_client(
            url=os.environ.get("MCP_SERVER_URL", "{mcp_url}"),
            headers={{
                "Galileo-API-Key": os.environ["GALILEO_API_KEY"],
                "Accept": "text/event-stream",
            }},
        )
    )
    session = await stack.enter_async_context(ClientSession(read, write))
    await session.initialize()
    tools = await session.list_tools()
    return stack, session, tools.tools

async def call_and_log_tool(session, tool_name, arguments, tool_call_id, query):
    logger = galileo_context.get_logger_instance()
    start_ns = datetime.now().timestamp() * 1_000_000_000
    result = await session.call_tool(tool_name, arguments)
    logger.add_tool_span(
        input=query,
        output=result.content[0].text if result.content else "",
        name=tool_name,
        tool_call_id=tool_call_id,
        duration_ns=int((datetime.now().timestamp() * 1_000_000_000) - start_ns),
    )
    return result
```

## Notes

- Start a Galileo session and trace around the user conversation.
- Pass MCP tool schemas to the LLM only when tool use is desired.
- Log tool spans after each MCP call, including failures when possible.
- For complete runtime wiring or Splunk export, hand off to
  `galileo-platform-setup`.
"""


def render_metadata(
    clients: list[str],
    mcp_url: str,
    accept_write_tools: bool,
    key_file: str,
    server_names: dict[str, str],
    console_url: str,
) -> str:
    payload = {
        "skill": SKILL_NAME,
        "mcp_url": mcp_url,
        "galileo_console_url": console_url,
        "clients": clients,
        "server_names": {client: server_names[client] for client in clients},
        "accept_galileo_mcp_write_tools": accept_write_tools,
        "expected_server": {
            "name": EXPECTED_SERVER_NAME,
            "version_observed": EXPECTED_SERVER_VERSION,
        },
        "expected_tool_count": len(TOOL_CATALOG),
        "expected_tools": [
            {
                "name": tool["name"],
                "risk_group": tool["risk_group"],
                "required": tool["required"],
                "properties": tool["properties"],
                "schema_sha256": tool["schema_sha256"],
            }
            for tool in TOOL_CATALOG
        ],
        "expected_prompts_count": 0,
        "expected_resources_count": 0,
        "galileo_api_key_file_provided": bool(key_file),
    }
    return json_text(payload)


def rendered_plan(
    args: argparse.Namespace,
    clients: list[str],
    mcp_url: str,
    accept_write_tools: bool,
    server_names: dict[str, str],
    console_url: str,
) -> dict[str, Any]:
    files: list[str] = [
        "mcp/README.md",
        "metadata.json",
        "coverage/product-gap-matrix.json",
        "coverage/tool-catalog.json",
    ]
    if "cursor" in clients:
        files.append("mcp/cursor.mcp.json")
    if "vscode" in clients:
        files.append("mcp/vscode.mcp.json")
    if any(client in clients for client in ("codex", "claude", "kiro")):
        files.extend(
            ["mcp/run-galileo-mcp.js", "mcp/run-galileo-mcp.sh", "mcp/.env.galileo-mcp.example"]
        )
    if "codex" in clients:
        files.append("mcp/codex-register-galileo-mcp.sh")
    if "claude" in clients:
        files.append("mcp/claude.mcp.json")
    if "kiro" in clients:
        files.append("mcp/kiro.mcp.json")
    files.append("observability/mcp-tool-span-logging.md")
    return {
        "skill": SKILL_NAME,
        "output_dir": str(Path(args.output_dir).resolve()),
        "mcp_url": mcp_url,
        "galileo_console_url": console_url,
        "clients": clients,
        "server_names": {client: server_names[client] for client in clients},
        "accept_galileo_mcp_write_tools": accept_write_tools,
        "rendered_files": files,
    }


def main() -> int:
    args = parse_args()
    config = build_config(args, load_spec(args.spec))
    clients = config["clients"]
    mcp_url = config["mcp_url"]
    console_url = config["galileo_console_url"]
    accept_write_tools = config["accept_write_tools"]
    server_names = config["server_names"]

    if args.dry_run:
        plan = rendered_plan(args, clients, mcp_url, accept_write_tools, server_names, console_url)
        if args.json:
            print(json_text(plan), end="")
        else:
            print("Galileo MCP Server render plan")
            print(f"Output directory: {plan['output_dir']}")
            print(f"MCP URL: {plan['mcp_url']}")
            print(f"Galileo console URL: {plan['galileo_console_url'] or '<not supplied>'}")
            print(f"Clients: {', '.join(plan['clients'])}")
            for file_name in plan["rendered_files"]:
                print(f"  render: {file_name}")
        return 0

    output_dir = Path(args.output_dir)
    mcp_dir = output_dir / "mcp"
    coverage_dir = output_dir / "coverage"
    observability_dir = output_dir / "observability"
    bridge_js = mcp_dir / "run-galileo-mcp.js"

    output_dir.mkdir(parents=True, exist_ok=True)

    if "cursor" in clients:
        write_text(mcp_dir / "cursor.mcp.json", cursor_config(mcp_url, server_names["cursor"]))
    if "vscode" in clients:
        write_text(mcp_dir / "vscode.mcp.json", vscode_config(mcp_url, server_names["vscode"]))
    if any(client in clients for client in ("codex", "claude", "kiro")):
        write_text(bridge_js, bridge_js_script(), executable=True)
        write_text(mcp_dir / "run-galileo-mcp.sh", bridge_shell_script(), executable=True)
        write_text(mcp_dir / ".env.galileo-mcp.example", bridge_env_example(mcp_url))
    if "codex" in clients:
        write_text(
            mcp_dir / "codex-register-galileo-mcp.sh",
            codex_register_script(bridge_js, server_names["codex"]),
            executable=True,
        )
    if "claude" in clients:
        write_text(mcp_dir / "claude.mcp.json", stdio_config(server_names["claude"], bridge_js))
    if "kiro" in clients:
        write_text(mcp_dir / "kiro.mcp.json", stdio_config(server_names["kiro"], bridge_js))

    write_text(mcp_dir / "README.md", render_readme(clients, mcp_url, accept_write_tools))
    write_text(
        coverage_dir / "product-gap-matrix.json",
        json_text({"skill": SKILL_NAME, "product_gap_matrix": PRODUCT_GAP_MATRIX}),
    )
    write_text(
        coverage_dir / "tool-catalog.json",
        json_text(tool_catalog_payload()),
    )
    write_text(
        observability_dir / "mcp-tool-span-logging.md",
        render_observability_handoff(mcp_url),
    )
    write_text(
        output_dir / "metadata.json",
        render_metadata(
            clients,
            mcp_url,
            accept_write_tools,
            config["galileo_api_key_file"],
            server_names,
            console_url,
        ),
    )
    print(f"Rendered Galileo MCP assets to {output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
