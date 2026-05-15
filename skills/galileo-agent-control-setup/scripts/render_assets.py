#!/usr/bin/env python3
"""Render Galileo Agent Control setup assets.

The renderer is intentionally offline. It never reads token files and writes
only commands and examples that reference secret file paths.
"""

from __future__ import annotations

import argparse
import json
import re
import stat
import sys
from pathlib import Path
from typing import Any


SKILL_NAME = "galileo-agent-control-setup"
APPLY_SECTIONS = [
    "server",
    "auth",
    "controls",
    "python-runtime",
    "typescript-runtime",
    "otel-sink",
    "splunk-sink",
    "splunk-hec",
    "otel-collector",
    "dashboards",
    "detectors",
]
DIRECT_SECRET_FLAGS = {
    "--access-token",
    "--agent-control-admin-key",
    "--agent-control-api-key",
    "--api-key",
    "--api-token",
    "--authorization",
    "--bearer-token",
    "--hec-token",
    "--o11y-token",
    "--password",
    "--sf-token",
    "--splunk-hec-token",
    "--token",
}


def reject_direct_secret_flags(argv: list[str]) -> None:
    for arg in argv:
        flag = arg.split("=", 1)[0] if arg.startswith("--") else arg
        if flag in DIRECT_SECRET_FLAGS:
            print(
                f"ERROR: Direct secret flag {flag} is blocked. Use "
                "--agent-control-api-key-file, --agent-control-admin-key-file, "
                "--splunk-hec-token-file, or --o11y-token-file.",
                file=sys.stderr,
            )
            raise SystemExit(2)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    reject_direct_secret_flags(raw_args)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--spec", default="")
    parser.add_argument("--apply", default="")
    parser.add_argument("--server-url", default="")
    parser.add_argument("--server-host", default="")
    parser.add_argument("--server-port", default="")
    parser.add_argument("--agent-name", default="")
    parser.add_argument("--agent-description", default="")
    parser.add_argument("--deployment-environment", default="")
    parser.add_argument("--service-name", default="")
    parser.add_argument("--otlp-endpoint", default="")
    parser.add_argument("--splunk-platform", choices=["enterprise", "cloud"], default="")
    parser.add_argument("--splunk-hec-url", default="")
    parser.add_argument("--splunk-hec-token-file", default="")
    parser.add_argument("--splunk-index", default="")
    parser.add_argument("--splunk-source", default="")
    parser.add_argument("--splunk-sourcetype", default="")
    parser.add_argument("--hec-token-name", default="")
    parser.add_argument("--hec-allowed-indexes", default="")
    parser.add_argument("--realm", default="")
    parser.add_argument("--o11y-token-file", default="")
    parser.add_argument("--collector-cluster-name", default="")
    parser.add_argument("--runtime-target-dir", default="")
    parser.add_argument("--agent-control-api-key-file", default="")
    parser.add_argument("--agent-control-admin-key-file", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(raw_args)


def parse_simple_yaml(text: str) -> dict[str, Any] | None:
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line.strip().startswith("- "):
            return None
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()
        if ":" not in stripped:
            return None
        key, raw_value = stripped.split(":", 1)
        value = raw_value.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            return None
        current = stack[-1][1]
        if value == "":
            child: dict[str, Any] = {}
            current[key.strip()] = child
            stack.append((indent, child))
            continue
        if value.startswith(("'", '"')) and value.endswith(("'", '"')) and len(value) >= 2:
            value = value[1:-1]
        current[key.strip()] = value
    return root


def reject_inline_secrets(node: Any, path: str = "") -> None:
    secret_keys = {
        "access_token",
        "admin_key",
        "agent_control_admin_key",
        "agent_control_api_key",
        "api_key",
        "api_token",
        "authorization",
        "bearer_token",
        "hec_token",
        "o11y_token",
        "password",
        "secret",
        "splunk_hec_token",
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


def merge_config(args: argparse.Namespace, spec: dict[str, Any]) -> dict[str, Any]:
    def arg_or_spec(arg_name: str, spec_key: str, default: str = "") -> str:
        value = getattr(args, arg_name)
        if value not in ("", None):
            return str(value)
        return str(get_nested(spec, spec_key, default) or "")

    index = arg_or_spec("splunk_index", "splunk.index", "agent_control")
    allowed = arg_or_spec("hec_allowed_indexes", "splunk.hec_allowed_indexes", "") or index
    return {
        "server_url": arg_or_spec("server_url", "agent_control.server_url", "http://localhost:8000"),
        "server_host": arg_or_spec("server_host", "agent_control.server_host", "0.0.0.0"),
        "server_port": arg_or_spec("server_port", "agent_control.server_port", "8000"),
        "agent_name": arg_or_spec("agent_name", "agent.name", "splunk-governed-agent"),
        "agent_description": arg_or_spec(
            "agent_description",
            "agent.description",
            "Agent protected by Galileo Agent Control.",
        ),
        "deployment_environment": arg_or_spec(
            "deployment_environment",
            "runtime.deployment_environment",
            "production",
        ),
        "service_name": arg_or_spec("service_name", "runtime.service_name", "agent-control-runtime"),
        "otlp_endpoint": arg_or_spec("otlp_endpoint", "otel.endpoint", "http://localhost:4318/v1/traces"),
        "splunk_platform": arg_or_spec("splunk_platform", "splunk.platform", "enterprise"),
        "splunk_hec_url": arg_or_spec("splunk_hec_url", "splunk.hec_url", ""),
        "splunk_hec_token_file": arg_or_spec(
            "splunk_hec_token_file",
            "secrets.splunk_hec_token_file",
            "",
        ),
        "splunk_index": index,
        "splunk_source": arg_or_spec("splunk_source", "splunk.source", "agent-control"),
        "splunk_sourcetype": arg_or_spec(
            "splunk_sourcetype",
            "splunk.sourcetype",
            "agent_control:events:json",
        ),
        "hec_token_name": arg_or_spec("hec_token_name", "splunk.hec_token_name", "agent_control_events"),
        "hec_allowed_indexes": allowed,
        "realm": arg_or_spec("realm", "splunk_observability.realm", ""),
        "o11y_token_file": arg_or_spec("o11y_token_file", "secrets.o11y_token_file", ""),
        "collector_cluster_name": arg_or_spec(
            "collector_cluster_name",
            "collector.cluster_name",
            "agent-control",
        ),
        "runtime_target_dir": arg_or_spec("runtime_target_dir", "runtime.target_dir", ""),
        "agent_control_api_key_file": arg_or_spec(
            "agent_control_api_key_file",
            "secrets.agent_control_api_key_file",
            "",
        ),
        "agent_control_admin_key_file": arg_or_spec(
            "agent_control_admin_key_file",
            "secrets.agent_control_admin_key_file",
            "",
        ),
    }


def selected_sections(value: str) -> list[str]:
    if not value or value == "all":
        return list(APPLY_SECTIONS)
    sections = [item.strip() for item in value.split(",") if item.strip()]
    unknown = sorted(set(sections) - set(APPLY_SECTIONS))
    if unknown:
        raise SystemExit(f"ERROR: Unknown apply section(s): {', '.join(unknown)}")
    return sections


def write_text(path: Path, text: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def shell_double_default(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "\\$")
        .replace("`", "\\`")
    )


def script_header() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "${OUTPUT_DIR}/../.." && pwd)}"
"""


def require_file_var(var_name: str, default_path: str, label: str) -> str:
    default = shell_double_default(default_path)
    return f"""
{var_name}="${{{var_name}:-{default}}}"
if [[ -z "${{{var_name}}}" ]]; then
  echo "ERROR: {label} is required. Set {var_name} or re-render with its file flag." >&2
  exit 1
fi
if [[ ! -r "${{{var_name}}}" ]]; then
  echo "ERROR: {label} is not readable: ${{{var_name}}}" >&2
  exit 1
fi
"""


def render_metadata(output_dir: Path, config: dict[str, Any]) -> None:
    write_json(
        output_dir / "metadata.json",
        {
            "api_version": f"{SKILL_NAME}/v1",
            "server_url": config["server_url"],
            "agent_name": config["agent_name"],
            "secret_values_rendered": False,
        },
    )


def render_server_auth(output_dir: Path, config: dict[str, Any]) -> None:
    write_text(
        output_dir / "server/docker-compose.env.example",
        f"""AGENT_CONTROL_SERVER_HOST_PORT={config["server_port"]}
AGENT_CONTROL_API_KEY_ENABLED=true
AGENT_CONTROL_API_KEYS_FILE={shell_quote(config["agent_control_api_key_file"])}
AGENT_CONTROL_ADMIN_API_KEYS_FILE={shell_quote(config["agent_control_admin_key_file"])}
AGENT_CONTROL_POSTGRES_PASSWORD_FILE=/path/to/postgres_password
""",
    )
    write_text(
        output_dir / "server/external-server-readiness.md",
        f"""# Agent Control Server Readiness

- Server URL: `{config["server_url"]}`
- Health endpoint: `{config["server_url"].rstrip("/")}/health`
- Auth enabled: expected for production
- Agent API key file: `{config["agent_control_api_key_file"] or "<path-required>"}`
- Admin API key file: `{config["agent_control_admin_key_file"] or "<path-required>"}`

For Docker quick starts, prefer a local env file and file-backed secret loading.
For external servers, confirm TLS termination, API key enforcement, admin API
separation, and network reachability from protected agents.
""",
    )
    write_text(
        output_dir / "auth/agent-control-auth.env.example",
        f"""AGENT_CONTROL_BASE_URL={shell_quote(config["server_url"])}
AGENT_CONTROL_API_KEY_FILE={shell_quote(config["agent_control_api_key_file"])}
AGENT_CONTROL_ADMIN_API_KEY_FILE={shell_quote(config["agent_control_admin_key_file"])}
AGENT_CONTROL_API_KEY_ENABLED=true
""",
    )


def render_controls(output_dir: Path, config: dict[str, Any]) -> None:
    write_json(
        output_dir / "controls/policy-templates.json",
        {
            "api_version": f"{SKILL_NAME}/controls/v1",
            "controls": [
                {
                    "name": "observe-all-llm-and-tool-steps",
                    "description": "Observe every LLM and tool step before enforcing blocking policy.",
                    "enabled": True,
                    "execution": "server",
                    "scope": {"step_types": ["llm", "tool"], "stages": ["pre", "post"]},
                    "condition": {
                        "selector": {"path": "input"},
                        "evaluator": {"name": "regex", "config": {"pattern": ".+"}},
                    },
                    "action": {"decision": "observe"},
                },
                {
                    "name": "block-ssn-output",
                    "description": "Starter post-execution PII block for social security number patterns.",
                    "enabled": True,
                    "execution": "server",
                    "scope": {"step_types": ["tool", "llm"], "stages": ["post"]},
                    "condition": {
                        "selector": {"path": "output"},
                        "evaluator": {
                            "name": "regex",
                            "config": {"pattern": r"\b\d{3}-\d{2}-\d{4}\b"},
                        },
                    },
                    "action": {
                        "decision": "deny",
                        "metadata": {"reason": "SSN detected", "compliance": "PII protection"},
                    },
                },
            ],
            "notes": [
                "Agent Control applies deny-wins semantics; any matching deny blocks the request.",
                "Start with observe controls before enabling deny in production.",
            ],
        },
    )


def render_runtime(output_dir: Path, config: dict[str, Any]) -> None:
    write_text(
        output_dir / "runtime/python-control.py",
        f'''"""Agent Control Python runtime snippet.

Read AGENT_CONTROL_API_KEY from AGENT_CONTROL_API_KEY_FILE before importing
agent_control in production entrypoints.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import agent_control
from agent_control import ControlViolationError, control


def _read_secret_file(env_name: str) -> str:
    path = os.environ.get(env_name, "")
    if not path:
        raise RuntimeError(f"{{env_name}} is required")
    return Path(path).read_text(encoding="utf-8").strip()


def init_agent_control() -> None:
    os.environ.setdefault("AGENT_CONTROL_BASE_URL", {config["server_url"]!r})
    if "AGENT_CONTROL_API_KEY" not in os.environ:
        os.environ["AGENT_CONTROL_API_KEY"] = _read_secret_file("AGENT_CONTROL_API_KEY_FILE")
    agent_control.init(
        agent_name={config["agent_name"]!r},
        agent_description={config["agent_description"]!r},
    )


@control()
async def guarded_chat(message: str) -> str:
    return f"Echo: {{message}}"


async def main() -> None:
    init_agent_control()
    try:
        print(await guarded_chat("hello"))
    except ControlViolationError as exc:
        print(f"Blocked by control: {{exc.control_name}}")
    finally:
        await agent_control.ashutdown()


if __name__ == "__main__":
    asyncio.run(main())
''',
    )
    write_text(
        output_dir / "runtime/typescript-control.ts",
        f"""// Agent Control TypeScript runtime skeleton.
// Keep API key loading in your runtime secret manager; do not inline keys.

const agentName = {json.dumps(config["agent_name"])};
const serverUrl = process.env.AGENT_CONTROL_BASE_URL ?? {json.dumps(config["server_url"])};

export async function initAgentControl() {{
  const apiKeyFile = process.env.AGENT_CONTROL_API_KEY_FILE;
  if (!apiKeyFile) throw new Error("AGENT_CONTROL_API_KEY_FILE is required");
  return {{ agentName, serverUrl, apiKeyFile }};
}}

export async function guardedTool(input: string): Promise<string> {{
  return `Echo: ${{input}}`;
}}
""",
    )


def render_sinks(output_dir: Path, config: dict[str, Any]) -> None:
    write_text(
        output_dir / "sinks/otel-sink.env",
        f"""AGENT_CONTROL_OBSERVABILITY_SINK_NAME=otel
AGENT_CONTROL_OTEL_ENABLED=true
AGENT_CONTROL_OTEL_ENDPOINT={shell_quote(config["otlp_endpoint"])}
AGENT_CONTROL_OTEL_SERVICE_NAME={shell_quote(config["service_name"])}
OTEL_RESOURCE_ATTRIBUTES={shell_quote("deployment.environment=" + config["deployment_environment"])}
""",
    )
    write_text(
        output_dir / "sinks/splunk-hec-sink.py",
        f'''"""Custom Agent Control event sink for Splunk HEC.

The HEC token is read from SPLUNK_HEC_TOKEN_FILE. Events are sent as JSON
objects using sourcetype {config["splunk_sourcetype"]!r}.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable
from urllib import request

from agent_control import register_control_event_sink
from agent_control_telemetry import BaseControlEventSink, SinkResult


def _read_secret_file(env_name: str) -> str:
    path = os.environ.get(env_name, "")
    if not path:
        raise RuntimeError(f"{{env_name}} is required")
    return Path(path).read_text(encoding="utf-8").strip()


class SplunkHecControlEventSink(BaseControlEventSink):
    def __init__(self) -> None:
        base_url = os.environ.get("SPLUNK_HEC_URL", {config["splunk_hec_url"]!r}).rstrip("/")
        if "/services/collector" in base_url:
            self.url = base_url
        else:
            self.url = base_url + "/services/collector/event"
        self.token = _read_secret_file("SPLUNK_HEC_TOKEN_FILE")

    def write_events(self, events: Iterable[object]) -> SinkResult:
        accepted = 0
        for event in events:
            payload = event.model_dump(mode="json") if hasattr(event, "model_dump") else dict(event)
            envelope = {{
                "source": {config["splunk_source"]!r},
                "sourcetype": {config["splunk_sourcetype"]!r},
                "index": {config["splunk_index"]!r},
                "event": payload,
            }}
            req = request.Request(
                self.url,
                method="POST",
                data=json.dumps(envelope).encode("utf-8"),
                headers={{"Authorization": f"Splunk {{self.token}}", "Content-Type": "application/json"}},
            )
            with request.urlopen(req, timeout=30):
                accepted += 1
        return SinkResult(accepted=accepted, dropped=0)


def register_splunk_hec_sink() -> SplunkHecControlEventSink:
    sink = SplunkHecControlEventSink()
    register_control_event_sink(sink)
    return sink
''',
    )
    write_text(
        output_dir / "sinks/splunk-hec-event-sample.json",
        json.dumps(
            {
                "source": config["splunk_source"],
                "sourcetype": config["splunk_sourcetype"],
                "index": config["splunk_index"],
                "event": {
                    "agent_name": config["agent_name"],
                    "control_name": "block-ssn-output",
                    "decision": "deny",
                    "stage": "post",
                },
            },
            indent=2,
        )
        + "\n",
    )


def render_o11y_specs(output_dir: Path, config: dict[str, Any]) -> None:
    realm = config["realm"] or "us0"
    service = config["service_name"]
    write_text(
        output_dir / "dashboards/agent-control-dashboard.yaml",
        f"""api_version: splunk-observability-dashboard-builder/v1
mode: classic-api
realm: {realm}
dashboard_group:
  name: Agent Control
  description: Agent Control governance events.
dashboard:
  name: Agent Control Operations
  description: Runtime control decisions and sink health.
charts:
  - id: control-volume
    name: Control event volume
    type: TimeSeriesChart
    plot_type: LineChart
    row: 0
    column: 0
    width: 6
    height: 1
    program_text: |
      data('spans.count', filter=filter('service.name', '{service}')).sum().publish(label='events')
""",
    )
    write_text(
        output_dir / "detectors/agent-control-detectors.yaml",
        f"""api_version: splunk-observability-native-ops/v1
realm: {realm}
detectors:
  - name: Agent Control deny spike
    description: Starter detector for a spike in denied control events.
    program_text: |
      denies = data('spans.count', filter=filter('service.name', '{service}')).sum().publish(label='denies')
      detect(when(denies > threshold(10))).publish('agent_control_denies')
    tags:
      - agent-control
    rules:
      - detect_label: agent_control_denies
        severity: Major
        description: Review active Agent Control deny decisions.
""",
    )


def render_scripts(output_dir: Path, config: dict[str, Any], sections: list[str]) -> dict[str, str]:
    scripts: dict[str, str] = {}
    scripts_dir = output_dir / "scripts"

    simple_messages = {
        "server": "Review server/docker-compose.env.example and server/external-server-readiness.md",
        "auth": "Review auth/agent-control-auth.env.example",
        "controls": "Review controls/policy-templates.json",
        "otel-sink": "Review sinks/otel-sink.env",
        "splunk-sink": "Review sinks/splunk-hec-sink.py",
    }
    for section, message in simple_messages.items():
        script = f"""{script_header()}
echo {shell_quote(message)}
"""
        write_text(scripts_dir / f"apply-{section}.sh", script, executable=True)
        scripts[section] = f"scripts/apply-{section}.sh"

    python_runtime = f"""{script_header()}
TARGET_DIR="${{RUNTIME_TARGET_DIR:-{shell_double_default(config["runtime_target_dir"])}}}"
if [[ -z "${{TARGET_DIR}}" ]]; then
  echo "Set RUNTIME_TARGET_DIR to copy runtime/python-control.py into an app tree." >&2
  echo "Rendered snippet: ${{OUTPUT_DIR}}/runtime/python-control.py" >&2
  exit 0
fi
mkdir -p "${{TARGET_DIR}}"
cp "${{OUTPUT_DIR}}/runtime/python-control.py" "${{TARGET_DIR}}/agent_control_runtime.py"
echo "Installed Agent Control Python snippet into ${{TARGET_DIR}}/agent_control_runtime.py"
"""
    write_text(scripts_dir / "apply-python-runtime.sh", python_runtime, executable=True)
    scripts["python-runtime"] = "scripts/apply-python-runtime.sh"

    ts_runtime = f"""{script_header()}
TARGET_DIR="${{RUNTIME_TARGET_DIR:-{shell_double_default(config["runtime_target_dir"])}}}"
if [[ -z "${{TARGET_DIR}}" ]]; then
  echo "Set RUNTIME_TARGET_DIR to copy runtime/typescript-control.ts into an app tree." >&2
  echo "Rendered snippet: ${{OUTPUT_DIR}}/runtime/typescript-control.ts" >&2
  exit 0
fi
mkdir -p "${{TARGET_DIR}}"
cp "${{OUTPUT_DIR}}/runtime/typescript-control.ts" "${{TARGET_DIR}}/agent-control-runtime.ts"
echo "Installed Agent Control TypeScript snippet into ${{TARGET_DIR}}/agent-control-runtime.ts"
"""
    write_text(scripts_dir / "apply-typescript-runtime.sh", ts_runtime, executable=True)
    scripts["typescript-runtime"] = "scripts/apply-typescript-runtime.sh"

    splunk_hec = f"""{script_header()}
{require_file_var("SPLUNK_HEC_TOKEN_FILE", config["splunk_hec_token_file"], "--splunk-hec-token-file")}
exec bash "${{PROJECT_ROOT}}/skills/splunk-hec-service-setup/scripts/setup.sh" \\
  --platform {shell_quote(config["splunk_platform"])} \\
  --phase apply \\
  --token-name {shell_quote(config["hec_token_name"])} \\
  --description {shell_quote("Managed for Agent Control event sink")} \\
  --default-index {shell_quote(config["splunk_index"])} \\
  --allowed-indexes {shell_quote(config["hec_allowed_indexes"])} \\
  --source {shell_quote(config["splunk_source"])} \\
  --sourcetype {shell_quote(config["splunk_sourcetype"])} \\
  --token-file "${{SPLUNK_HEC_TOKEN_FILE}}"
"""
    write_text(scripts_dir / "apply-splunk-hec.sh", splunk_hec, executable=True)
    scripts["splunk-hec"] = "scripts/apply-splunk-hec.sh"

    otel_collector = f"""{script_header()}
{require_file_var("O11Y_TOKEN_FILE", config["o11y_token_file"], "--o11y-token-file")}
if [[ -z {shell_quote(config["realm"])} ]]; then
  echo "ERROR: --realm is required for the otel-collector handoff." >&2
  exit 1
fi
exec bash "${{PROJECT_ROOT}}/skills/splunk-observability-otel-collector-setup/scripts/setup.sh" \\
  --render-k8s \\
  --render-linux \\
  --realm {shell_quote(config["realm"])} \\
  --cluster-name {shell_quote(config["collector_cluster_name"])} \\
  --deployment-environment {shell_quote(config["deployment_environment"])} \\
  --service-name {shell_quote(config["service_name"])} \\
  --o11y-token-file "${{O11Y_TOKEN_FILE}}" \\
  --output-dir "${{OUTPUT_DIR}}/delegated/splunk-otel-collector"
"""
    write_text(scripts_dir / "apply-otel-collector.sh", otel_collector, executable=True)
    scripts["otel-collector"] = "scripts/apply-otel-collector.sh"

    dashboards = f"""{script_header()}
{require_file_var("O11Y_TOKEN_FILE", config["o11y_token_file"], "--o11y-token-file")}
exec bash "${{PROJECT_ROOT}}/skills/splunk-observability-dashboard-builder/scripts/setup.sh" \\
  --apply \\
  --spec "${{OUTPUT_DIR}}/dashboards/agent-control-dashboard.yaml" \\
  --realm {shell_quote(config["realm"] or "us0")} \\
  --token-file "${{O11Y_TOKEN_FILE}}" \\
  --output-dir "${{OUTPUT_DIR}}/delegated/dashboards"
"""
    write_text(scripts_dir / "apply-dashboards.sh", dashboards, executable=True)
    scripts["dashboards"] = "scripts/apply-dashboards.sh"

    detectors = f"""{script_header()}
{require_file_var("O11Y_TOKEN_FILE", config["o11y_token_file"], "--o11y-token-file")}
exec bash "${{PROJECT_ROOT}}/skills/splunk-observability-native-ops/scripts/setup.sh" \\
  --apply \\
  --spec "${{OUTPUT_DIR}}/detectors/agent-control-detectors.yaml" \\
  --realm {shell_quote(config["realm"] or "us0")} \\
  --token-file "${{O11Y_TOKEN_FILE}}" \\
  --output-dir "${{OUTPUT_DIR}}/delegated/detectors"
"""
    write_text(scripts_dir / "apply-detectors.sh", detectors, executable=True)
    scripts["detectors"] = "scripts/apply-detectors.sh"

    apply_lines = [script_header(), "sections=(" + " ".join(shell_quote(s) for s in sections) + ")\n"]
    apply_lines.append(
        """for section in "${sections[@]}"; do
  "${SCRIPT_DIR}/apply-${section}.sh"
done
"""
    )
    write_text(scripts_dir / "apply-selected.sh", "".join(apply_lines), executable=True)
    scripts["selected"] = "scripts/apply-selected.sh"
    return scripts


def build_apply_plan(
    config: dict[str, Any], scripts: dict[str, str], sections: list[str], output_dir: Path
) -> dict[str, Any]:
    targets = {
        "server": "galileo-agent-control-setup",
        "auth": "galileo-agent-control-setup",
        "controls": "galileo-agent-control-setup",
        "python-runtime": "galileo-agent-control-setup",
        "typescript-runtime": "galileo-agent-control-setup",
        "otel-sink": "galileo-agent-control-setup",
        "splunk-sink": "galileo-agent-control-setup",
        "splunk-hec": "splunk-hec-service-setup",
        "otel-collector": "splunk-observability-otel-collector-setup",
        "dashboards": "splunk-observability-dashboard-builder",
        "detectors": "splunk-observability-native-ops",
    }
    return {
        "api_version": f"{SKILL_NAME}/v1",
        "output_dir": str(output_dir),
        "selected_sections": sections,
        "sections": [
            {
                "name": section,
                "delegates_to": targets[section],
                "script": scripts[section],
                "secret_values_rendered": False,
            }
            for section in APPLY_SECTIONS
        ],
        "secret_files": {
            "agent_control_api_key_file": config["agent_control_api_key_file"],
            "agent_control_admin_key_file": config["agent_control_admin_key_file"],
            "splunk_hec_token_file": config["splunk_hec_token_file"],
            "o11y_token_file": config["o11y_token_file"],
        },
        "paths": {
            "metadata": "metadata.json",
            "apply_plan": "apply-plan.json",
            "coverage_report": "coverage-report.json",
            "handoff": "handoff.md",
            "server": "server/",
            "auth": "auth/",
            "controls": "controls/",
            "runtime": "runtime/",
            "sinks": "sinks/",
            "scripts": "scripts/",
        },
    }


def build_coverage_report(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "api_version": f"{SKILL_NAME}/coverage/v1",
        "status": "rendered",
        "secret_values_rendered": False,
        "coverage": {
            "server_readiness": {"status": "rendered_handoff", "assets": ["server/"]},
            "auth": {"status": "rendered_handoff", "assets": ["auth/"]},
            "controls": {"status": "rendered_handoff", "assets": ["controls/policy-templates.json"]},
            "python_runtime": {"status": "rendered_handoff", "assets": ["runtime/python-control.py"]},
            "typescript_runtime": {"status": "rendered_handoff", "assets": ["runtime/typescript-control.ts"]},
            "otel_sink": {"status": "rendered_handoff", "assets": ["sinks/otel-sink.env"]},
            "splunk_sink": {"status": "rendered_handoff", "assets": ["sinks/splunk-hec-sink.py"]},
            "splunk_handoffs": {
                "status": "delegated",
                "delegates": [
                    "splunk-hec-service-setup",
                    "splunk-observability-otel-collector-setup",
                    "splunk-observability-dashboard-builder",
                    "splunk-observability-native-ops",
                ],
            },
        },
        "defaults": {
            "server_url": config["server_url"],
            "agent_name": config["agent_name"],
            "sourcetype": config["splunk_sourcetype"],
            "index": config["splunk_index"],
        },
    }


def render_handoff(output_dir: Path, scripts: dict[str, str]) -> None:
    lines = [
        "# Galileo Agent Control Handoff",
        "",
        "Rendered assets are offline by default and keep secret values in local files.",
        "",
        "## Apply Sections",
    ]
    for section in APPLY_SECTIONS:
        lines.append(f"- `{section}`: `{scripts[section]}`")
    lines.extend(
        [
            "",
            "## Delegation Targets",
            "- `splunk-hec` -> `splunk-hec-service-setup`",
            "- `otel-collector` -> `splunk-observability-otel-collector-setup`",
            "- `dashboards` -> `splunk-observability-dashboard-builder`",
            "- `detectors` -> `splunk-observability-native-ops`",
            "",
            "## First Validation",
            f"bash {scripts['selected'].replace('scripts/', str(output_dir / 'scripts') + '/')}",
            "",
        ]
    )
    write_text(output_dir / "handoff.md", "\n".join(lines))


def render(args: argparse.Namespace) -> dict[str, Any]:
    spec = load_spec(args.spec)
    config = merge_config(args, spec)
    sections = selected_sections(args.apply)
    output_dir = Path(args.output_dir).expanduser().resolve()
    scripts = {section: f"scripts/apply-{section}.sh" for section in APPLY_SECTIONS}
    scripts["selected"] = "scripts/apply-selected.sh"
    dry_plan = build_apply_plan(config, scripts, sections, output_dir)
    if args.dry_run:
        return dry_plan

    output_dir.mkdir(parents=True, exist_ok=True)
    render_metadata(output_dir, config)
    render_server_auth(output_dir, config)
    render_controls(output_dir, config)
    render_runtime(output_dir, config)
    render_sinks(output_dir, config)
    render_o11y_specs(output_dir, config)
    scripts = render_scripts(output_dir, config, sections)
    write_json(output_dir / "apply-plan.json", build_apply_plan(config, scripts, sections, output_dir))
    write_json(output_dir / "coverage-report.json", build_coverage_report(config))
    render_handoff(output_dir, scripts)
    return {
        "output_dir": str(output_dir),
        "apply_plan": str(output_dir / "apply-plan.json"),
        "coverage_report": str(output_dir / "coverage-report.json"),
        "handoff": str(output_dir / "handoff.md"),
        "selected_sections": sections,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = render(args)
    if args.json or args.dry_run:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Rendered Galileo Agent Control assets to {payload['output_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
