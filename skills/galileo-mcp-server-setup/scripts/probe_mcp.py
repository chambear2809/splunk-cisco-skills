"""Probe the Galileo MCP Server without mutating tenant objects."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse


DEFAULT_MCP_URL = "https://api.galileo.ai/mcp/http/mcp"
EXPECTED_SERVER_NAME = "EvalsInIDEServer"
EXPECTED_SERVER_VERSION = "1.27.1"
EXPECTED_TOOLS: dict[str, dict[str, Any]] = {
    "integrate_galileo_with_langchain": {
        "risk_group": "guidance_public",
        "required": ["language"],
        "properties": ["language"],
        "schema_sha256": "a6a782dc432bf60e09d42264f9533d86043e6e704d994bd9fe702d93b9c3c37c",
    },
    "integrate_galileo_with_openai": {
        "risk_group": "guidance_public",
        "required": ["language"],
        "properties": ["language"],
        "schema_sha256": "74131104916793729d7a6092b88a3766cade01f4668b16ba66e8981d8dbfd27f",
    },
    "get_logstream_insights": {
        "risk_group": "tenant_read",
        "required": ["project", "log_stream"],
        "properties": ["project", "log_stream"],
        "schema_sha256": "aec39521ea02e18fa32d88dc9bb1dc9c7e720cb79087704b0c55362b915b23bc",
    },
    "get_logstream_signals": {
        "risk_group": "tenant_read",
        "required": ["project", "log_stream"],
        "properties": ["project", "log_stream"],
        "schema_sha256": "628178ceae9e2f9c884c6c46ab4d4a7980f9ff4151cca266e164b5285a03244d",
    },
    "validate_dataset": {
        "risk_group": "tenant_read",
        "required": ["dataset_id"],
        "properties": ["dataset_id"],
        "schema_sha256": "eed688749cbb169a2090a90d3080e9a2b950251c1d0e7d21acab5a94aede7b0e",
    },
    "create_galileo_dataset": {
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
    },
    "create_prompt_template": {
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
    },
    "setup_galileo_experiment": {
        "risk_group": "guidance_public",
        "required": [],
        "properties": ["language"],
        "schema_sha256": "07dd26c2885f9bbaa49048a42d6188362b021f3931e4d15ca19424bd0fb32534",
    },
    "search_docs": {
        "risk_group": "guidance_public",
        "required": ["query"],
        "properties": ["query"],
        "schema_sha256": "9f109ec337868d70e1114f2dd32bda775e6bc09819e7bdfc3fedde07c64c2bd4",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mcp-url", default="")
    parser.add_argument("--galileo-console-url", default="")
    parser.add_argument("--galileo-api-key-file", default="")
    parser.add_argument("--auth-check", action="store_true")
    parser.add_argument(
        "--allow-loose-key-perms",
        action="store_true",
        help="Warn instead of failing when --galileo-api-key-file is not chmod 600.",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--fail-on-drift", action="store_true")
    return parser.parse_args()


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


def api_base_from_mcp_url(mcp_url: str) -> str:
    parsed = urlparse(mcp_url)
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", "")).rstrip("/")


def parse_sse_json(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    events: list[str] = []
    data_lines: list[str] = []
    for line in text.splitlines():
        if not line:
            if data_lines:
                events.append("\n".join(data_lines))
                data_lines = []
            continue
        if line.startswith("data:"):
            value = line[5:]
            if value.startswith(" "):
                value = value[1:]
            data_lines.append(value)
    if data_lines:
        events.append("\n".join(data_lines))

    for event in events:
        try:
            payload = json.loads(event)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise RuntimeError(f"No JSON-RPC data event found: {text[:200]!r}")


def rpc(mcp_url: str, method: str, params: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
    payload = {
        "jsonrpc": "2.0",
        "id": method,
        "method": method,
        "params": params or {},
    }
    if method == "initialize":
        payload["params"] = {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "galileo-mcp-server-setup-probe", "version": "0.0.0"},
        }
    request = urllib.request.Request(
        mcp_url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8", "replace")
    data = parse_sse_json(body)
    if "error" in data:
        raise RuntimeError(f"{method} failed: {data['error']}")
    return data.get("result") or {}


def check_key_permissions(target: Path, allow_loose: bool) -> None:
    mode = target.stat().st_mode & 0o777
    if mode == 0o600:
        return
    message = f"Galileo API key file {target} is mode {mode:o}; expected 600."
    if allow_loose:
        print(f"WARN: {message}", file=sys.stderr)
        return
    raise RuntimeError(message)


def read_secret_file(path: str, allow_loose: bool) -> str:
    if not path:
        raise RuntimeError("--auth-check requires --galileo-api-key-file")
    target = Path(path).expanduser()
    if not target.is_file():
        raise RuntimeError(f"Galileo API key file not found: {target}")
    check_key_permissions(target, allow_loose)
    key = target.read_text(encoding="utf-8").strip()
    if not key:
        raise RuntimeError(f"Galileo API key file is empty: {target}")
    return key


def auth_check(
    mcp_url: str, key_file: str, timeout: float, allow_loose_key_perms: bool
) -> dict[str, Any]:
    key = read_secret_file(key_file, allow_loose_key_perms)
    api_base = api_base_from_mcp_url(mcp_url)
    request = urllib.request.Request(
        f"{api_base}/v2/current_user",
        method="GET",
        headers={"Galileo-API-Key": key},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
        return {"ok": True, "status": 200, "user_keys": sorted(payload.keys())}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "error": exc.reason}


def tool_schema(tool: dict[str, Any]) -> dict[str, list[str]]:
    schema = tool.get("inputSchema") or {}
    properties = schema.get("properties") or {}
    return {
        "required": sorted(schema.get("required") or []),
        "properties": sorted(properties.keys()),
    }


def schema_hash(tool: dict[str, Any]) -> str:
    schema = tool.get("inputSchema") or {}
    canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def schema_drift(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    drift: list[dict[str, Any]] = []
    for tool in tools:
        name = tool.get("name", "")
        expected = EXPECTED_TOOLS.get(name)
        if not expected:
            continue
        live_schema = tool_schema(tool)
        expected_required = sorted(expected["required"])
        expected_properties = sorted(expected["properties"])
        if live_schema["required"] != expected_required:
            drift.append(
                {
                    "tool": name,
                    "field": "required",
                    "expected": expected_required,
                    "live": live_schema["required"],
                }
            )
        if live_schema["properties"] != expected_properties:
            drift.append(
                {
                    "tool": name,
                    "field": "properties",
                    "expected": expected_properties,
                    "live": live_schema["properties"],
                }
            )
        live_hash = schema_hash(tool)
        if live_hash != expected["schema_sha256"]:
            drift.append(
                {
                    "tool": name,
                    "field": "schema_sha256",
                    "expected": expected["schema_sha256"],
                    "live": live_hash,
                }
            )
    return drift


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    mcp_url = derive_mcp_url(args.mcp_url, args.galileo_console_url)
    initialize = rpc(mcp_url, "initialize", None, args.timeout)
    tools_result = rpc(mcp_url, "tools/list", {}, args.timeout)
    prompts_result = rpc(mcp_url, "prompts/list", {}, args.timeout)
    resources_result = rpc(mcp_url, "resources/list", {}, args.timeout)

    tools = tools_result.get("tools") or []
    live_names = [tool.get("name", "") for tool in tools]
    unknown = sorted(set(live_names) - set(EXPECTED_TOOLS))
    missing = sorted(set(EXPECTED_TOOLS) - set(live_names))
    schema_changes = schema_drift(tools)
    warnings: list[str] = []
    server = initialize.get("serverInfo") or {}
    if server.get("name") != EXPECTED_SERVER_NAME:
        warnings.append(
            f"Unexpected server name {server.get('name')!r}; expected {EXPECTED_SERVER_NAME!r}."
        )
    if server.get("version") != EXPECTED_SERVER_VERSION:
        warnings.append(
            f"Server version changed from observed {EXPECTED_SERVER_VERSION} to {server.get('version')}."
        )
    if unknown:
        warnings.append("Unknown live tools require manual approval: " + ", ".join(unknown))
    if missing:
        warnings.append("Expected tools missing from live server: " + ", ".join(missing))
    if schema_changes:
        warnings.append(
            "Live tool schemas changed and require catalog review: "
            + ", ".join(f"{item['tool']}.{item['field']}" for item in schema_changes)
        )
    prompts = prompts_result.get("prompts") or []
    resources = resources_result.get("resources") or []
    if prompts:
        warnings.append("Live prompts are now present and require catalog review.")
    if resources:
        warnings.append("Live resources are now present and require catalog review.")

    report = {
        "mcp_url": mcp_url,
        "server": server,
        "tool_count": len(live_names),
        "tools": [
            {
                "name": name,
                "risk_group": EXPECTED_TOOLS.get(name, {}).get(
                    "risk_group", "uncategorized_manual_approval"
                ),
                **tool_schema(tool),
                "schema_sha256": schema_hash(tool),
            }
            for name, tool in ((tool.get("name", ""), tool) for tool in tools)
        ],
        "prompts_count": len(prompts),
        "resources_count": len(resources),
        "unknown_tools": unknown,
        "missing_tools": missing,
        "schema_drift": schema_changes,
        "warnings": warnings,
    }
    if args.auth_check:
        report["auth_check"] = auth_check(
            mcp_url,
            args.galileo_api_key_file,
            args.timeout,
            args.allow_loose_key_perms,
        )
    return report


def main() -> int:
    args = parse_args()
    try:
        report = build_report(args)
    except Exception as exc:  # noqa: BLE001 - CLI probe should print concise diagnostics.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Galileo MCP URL: {report['mcp_url']}")
        print(f"Server: {report['server'].get('name')} {report['server'].get('version')}")
        print(f"Tools: {report['tool_count']}")
        for tool in report["tools"]:
            print(f"  - {tool['name']} [{tool['risk_group']}]")
        print(f"Prompts: {report['prompts_count']}")
        print(f"Resources: {report['resources_count']}")
        for warning in report["warnings"]:
            print(f"WARN: {warning}", file=sys.stderr)
        if "auth_check" in report:
            check = report["auth_check"]
            print(f"Auth check: status={check.get('status')} ok={check.get('ok')}")
    if args.fail_on_drift and (
        report["unknown_tools"]
        or report["missing_tools"]
        or report["schema_drift"]
        or report["prompts_count"]
        or report["resources_count"]
    ):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
