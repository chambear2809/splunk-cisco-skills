#!/usr/bin/env python3
"""Render and validate Splunk Observability instrumentation for Codex."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import SplitResult, urlsplit

from skills.shared.coding_agent_o11y.common import (
    REPO_ROOT,
    UsageError,
    command_failed,
    deep_merge,
    ensure_safe_external_header,
    ensure_safe_external_value,
    load_structured_file,
    parse_header,
    print_payload,
    reject_secret_argv,
    scan_rendered_for_secret_leaks,
    shell_join,
    split_csv,
    validate_toml_file,
    write_json,
    write_text,
)


SKILL_NAME = "splunk-observability-codex-instrumentation-setup"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "splunk-observability-codex-instrumentation-rendered"
VALID_DESTINATIONS = {"local-collector", "external-collector", "direct", "all"}
VALID_PROTOCOLS = {"otlp-http", "otlp-grpc"}
APPLY_SECTIONS = ("profiles", "runtime", "hooks", "env-helper")
MANAGED_HOOK_STATUS = "Capturing Codex O11y session metadata"


DEFAULT_SPEC: dict[str, Any] = {
    "api_version": "splunk-observability-codex-instrumentation-setup/v1",
    "codex": {
        "codex_home": "",
        "environment": "prod",
        "service_name": "codex-cli",
        "realm": "us0",
        "destination": "local-collector",
        "profile_prefix": "codex-o11y",
        "enable_native_logs": False,
        "enable_advanced_genai_spans": False,
        "content_capture": False,
        "accept_content_capture": False,
        "enable_ai_defense": False,
        "accept_ai_defense_content_inspection": False,
        "local_collector_endpoint": "http://127.0.0.1:14318",
        "external_collector_protocol": "otlp-http",
        "external_trace_endpoint": "",
        "external_metric_endpoint": "",
        "external_log_endpoint": "",
        "external_headers": {},
        "external_tls": {},
    },
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def toml_quote(value: str) -> str:
    return json.dumps(value)


def yaml_quote(value: str) -> str:
    return json.dumps(str(value))


def shell_quote(value: object) -> str:
    return shlex.quote(str(value))


def profile_name(destination: str, prefix: str) -> str:
    suffix = {"local-collector": "local", "external-collector": "external", "direct": "direct"}[destination]
    return f"{prefix}-{suffix}"


def destinations_for(value: str) -> list[str]:
    return ["local-collector", "external-collector", "direct"] if value == "all" else [value]


def parse_local_collector_endpoint(value: object) -> SplitResult:
    raw = str(value or "").strip()
    if not raw:
        raise UsageError("local_collector_endpoint is required")
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"}:
        raise UsageError("local_collector_endpoint must use http:// or https://")
    if not parsed.hostname:
        raise UsageError("local_collector_endpoint must include a host")
    if parsed.username or parsed.password:
        raise UsageError("local_collector_endpoint must not include credentials")
    try:
        port = parsed.port
    except ValueError as exc:
        raise UsageError(f"local_collector_endpoint has an invalid port: {exc}") from exc
    if port is None:
        raise UsageError("local_collector_endpoint must include an explicit port")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise UsageError("local_collector_endpoint must be a base URL such as http://localhost:14318")
    return parsed


def normalize_local_collector_endpoint(value: object) -> str:
    parsed = parse_local_collector_endpoint(value)
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def local_collector_receiver_endpoint(value: object) -> str:
    parsed = parse_local_collector_endpoint(value)
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{host}:{parsed.port}"


def resolve_codex_home(config: dict[str, Any]) -> Path:
    configured = str(config.get("codex", {}).get("codex_home") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    env_home = os.environ.get("CODEX_HOME", "").strip()
    if env_home:
        return Path(env_home).expanduser().resolve()
    return (Path.home() / ".codex").resolve()


def load_spec_with_args(args: argparse.Namespace) -> dict[str, Any]:
    spec = DEFAULT_SPEC
    if args.spec:
        spec = deep_merge(spec, load_structured_file(Path(args.spec).expanduser()))
    config = deep_merge({}, spec)
    codex = config.setdefault("codex", {})

    cli_updates = {
        "codex_home": args.codex_home,
        "environment": args.environment,
        "service_name": args.service_name,
        "realm": args.realm,
        "destination": args.destination,
        "local_collector_endpoint": args.local_collector_endpoint,
        "external_collector_protocol": args.external_collector_protocol,
        "external_trace_endpoint": args.external_trace_endpoint,
        "external_metric_endpoint": args.external_metric_endpoint,
        "external_log_endpoint": args.external_log_endpoint,
    }
    for key, value in cli_updates.items():
        if value not in (None, ""):
            codex[key] = value

    if args.enable_native_logs:
        codex["enable_native_logs"] = True
    if args.enable_advanced_genai_spans:
        codex["enable_advanced_genai_spans"] = True
    if args.accept_content_capture:
        codex["content_capture"] = True
        codex["accept_content_capture"] = True
    if args.enable_ai_defense:
        codex["enable_ai_defense"] = True
    if args.accept_ai_defense_content_inspection:
        codex["accept_ai_defense_content_inspection"] = True

    if args.external_header:
        headers = dict(codex.get("external_headers") or {})
        for raw in args.external_header:
            key, value = parse_header(raw)
            headers[key] = value
        codex["external_headers"] = headers

    tls = dict(codex.get("external_tls") or {})
    for key, value in {
        "ca-certificate": args.external_ca_certificate,
        "client-certificate": args.external_client_certificate,
        "client-private-key": args.external_client_private_key,
    }.items():
        if value:
            ensure_safe_external_value(f"TLS {key}", value)
            tls[key] = value
    codex["external_tls"] = tls
    return config


def validate_config(config: dict[str, Any]) -> tuple[list[str], list[str]]:
    codex = config["codex"]
    errors: list[str] = []
    warnings: list[str] = []

    destination = str(codex.get("destination", "local-collector"))
    if destination not in VALID_DESTINATIONS:
        errors.append(f"destination must be one of {', '.join(sorted(VALID_DESTINATIONS))}")
        return errors, warnings

    protocol = str(codex.get("external_collector_protocol", "otlp-http"))
    if protocol not in VALID_PROTOCOLS:
        errors.append("external_collector_protocol must be otlp-http or otlp-grpc")

    try:
        normalize_local_collector_endpoint(codex.get("local_collector_endpoint"))
    except UsageError as exc:
        errors.append(str(exc))

    if codex.get("content_capture") and not codex.get("accept_content_capture"):
        errors.append("prompt/response/tool-output capture requires --accept-content-capture")

    if codex.get("enable_ai_defense") and not codex.get("accept_ai_defense_content_inspection"):
        errors.append("AI Defense inspection requires --enable-ai-defense plus --accept-ai-defense-content-inspection")

    for target in destinations_for(destination):
        if target == "external-collector":
            if not codex.get("external_trace_endpoint"):
                errors.append("external collector mode requires --external-trace-endpoint")
            if not codex.get("external_metric_endpoint"):
                errors.append("external collector mode requires --external-metric-endpoint")
            if codex.get("enable_native_logs") and not codex.get("external_log_endpoint"):
                errors.append("native logs through an external collector require --external-log-endpoint")
        if target == "direct":
            if codex.get("enable_native_logs"):
                errors.append("direct Splunk ingest refuses native Codex logs; use local-collector or external-collector")
            if protocol == "otlp-grpc":
                errors.append("direct Splunk ingest supports OTLP/HTTP only; gRPC direct mode is refused")
            if not codex.get("realm"):
                errors.append("direct Splunk ingest requires --realm")

    if not codex.get("enable_advanced_genai_spans"):
        warnings.append("advanced GenAI span helpers are rendered but disabled by default in metadata-only mode")

    for key, value in (codex.get("external_headers") or {}).items():
        try:
            ensure_safe_external_header(str(key), str(value))
        except UsageError as exc:
            errors.append(str(exc))
    for key, value in (codex.get("external_tls") or {}).items():
        try:
            ensure_safe_external_value(f"TLS {key}", str(value))
        except UsageError as exc:
            errors.append(str(exc))

    return errors, warnings


def inline_table(values: dict[str, Any]) -> str:
    parts = []
    for key in sorted(values):
        value = values[key]
        if isinstance(value, dict):
            rendered = inline_table({str(k): v for k, v in value.items()})
        elif isinstance(value, bool):
            rendered = "true" if value else "false"
        else:
            rendered = toml_quote(str(value))
        parts.append(f"{toml_quote(str(key))} = {rendered}")
    return "{ " + ", ".join(parts) + " }"


def exporter_inline(protocol: str, endpoint: str, *, headers: dict[str, str] | None = None, tls: dict[str, str] | None = None) -> str:
    settings: dict[str, Any] = {"endpoint": endpoint}
    if protocol == "otlp-http":
        settings["protocol"] = "binary"
    if headers:
        settings["headers"] = headers
    if tls:
        settings["tls"] = tls
    return inline_table({protocol: settings})


def local_profile(config: dict[str, Any]) -> str:
    codex = config["codex"]
    endpoint = normalize_local_collector_endpoint(codex["local_collector_endpoint"])
    native = bool(codex.get("enable_native_logs"))
    exporter = exporter_inline("otlp-http", endpoint + "/v1/logs") if native else toml_quote("none")
    lines = [
        "# Codex OTel profile for a local OpenTelemetry Collector.",
        "# Install as $CODEX_HOME/codex-o11y-local.config.toml and run:",
        "#   codex --strict-config --profile codex-o11y-local",
        "",
        "[otel]",
        f"environment = {toml_quote(str(codex['environment']))}",
        "log_user_prompt = false",
        f"exporter = {exporter}",
        f"trace_exporter = {exporter_inline('otlp-http', endpoint + '/v1/traces')}",
        f"metrics_exporter = {exporter_inline('otlp-http', endpoint + '/v1/metrics')}",
        "",
    ]
    return "\n".join(lines)


def external_profile(config: dict[str, Any]) -> str:
    codex = config["codex"]
    protocol = str(codex["external_collector_protocol"])
    native = bool(codex.get("enable_native_logs"))
    headers = {str(k): str(v) for k, v in (codex.get("external_headers") or {}).items()}
    tls = {str(k): str(v) for k, v in (codex.get("external_tls") or {}).items()}
    common_kwargs = {"headers": headers or None, "tls": tls or None}
    exporter = (
        exporter_inline(protocol, str(codex["external_log_endpoint"]), **common_kwargs)
        if native
        else toml_quote("none")
    )
    lines = [
        "# Codex OTel profile for an external OTLP collector.",
        "# Install as $CODEX_HOME/codex-o11y-external.config.toml and run:",
        "#   codex --strict-config --profile codex-o11y-external",
        "",
        "[otel]",
        f"environment = {toml_quote(str(codex['environment']))}",
        "log_user_prompt = false",
        f"exporter = {exporter}",
        f"trace_exporter = {exporter_inline(protocol, str(codex['external_trace_endpoint']), **common_kwargs)}",
        f"metrics_exporter = {exporter_inline(protocol, str(codex['external_metric_endpoint']), **common_kwargs)}",
        "",
    ]
    return "\n".join(lines)


def direct_profile(config: dict[str, Any]) -> str:
    codex = config["codex"]
    realm = str(codex["realm"])
    base = f"https://ingest.{realm}.observability.splunkcloud.com"
    header = {"X-SF-TOKEN": "${SPLUNK_ACCESS_TOKEN}"}
    lines = [
        "# Codex direct Splunk Observability OTLP/HTTP profile.",
        "# Direct mode sends traces and metrics only. Native Codex logs stay disabled.",
        "# Install as $CODEX_HOME/codex-o11y-direct.config.toml and run:",
        "#   codex --strict-config --profile codex-o11y-direct",
        "",
        "[otel]",
        f"environment = {toml_quote(str(codex['environment']))}",
        "log_user_prompt = false",
        'exporter = "none"',
        f"trace_exporter = {exporter_inline('otlp-http', base + '/v2/trace/otlp', headers=header)}",
        f"metrics_exporter = {exporter_inline('otlp-http', base + '/v2/datapoint/otlp', headers=header)}",
        "",
    ]
    return "\n".join(lines)


def render_collector_overlay(config: dict[str, Any]) -> str:
    codex = config["codex"]
    realm = str(codex.get("realm") or "us0")
    native_logs = bool(codex.get("enable_native_logs"))
    receiver_endpoint = local_collector_receiver_endpoint(codex["local_collector_endpoint"])
    logs_pipeline = (
        """    logs/codex:
      receivers: [otlp/codex]
      processors: [resource/codex, batch/codex]
      exporters: [signalfx/codex]
"""
        if native_logs
        else ""
    )
    return f"""# Local collector overlay for Codex OTel.
# Merge into a Splunk Distribution of OpenTelemetry Collector gateway.
receivers:
  otlp/codex:
    protocols:
      http:
        endpoint: {yaml_quote(receiver_endpoint)}

processors:
  batch/codex: {{}}
  resource/codex:
    attributes:
      - key: service.name
        value: {yaml_quote(str(codex['service_name']))}
        action: upsert
      - key: deployment.environment
        value: {yaml_quote(str(codex['environment']))}
        action: upsert

exporters:
  otlphttp/codex_traces:
    traces_endpoint: {yaml_quote(f"https://ingest.{realm}.observability.splunkcloud.com/v2/trace/otlp")}
    headers:
      X-SF-TOKEN: "${{env:SPLUNK_ACCESS_TOKEN}}"
  signalfx/codex:
    realm: {yaml_quote(realm)}
    access_token: "${{env:SPLUNK_ACCESS_TOKEN}}"
    send_otlp_histograms: true

service:
  pipelines:
    traces/codex:
      receivers: [otlp/codex]
      processors: [resource/codex, batch/codex]
      exporters: [otlphttp/codex_traces, signalfx/codex]
    metrics/codex:
      receivers: [otlp/codex]
      processors: [resource/codex, batch/codex]
      exporters: [signalfx/codex]
{logs_pipeline}"""


def render_exec_wrapper(config: dict[str, Any]) -> str:
    codex = config["codex"]
    service_name = shell_quote(str(codex["service_name"]))
    environment = shell_quote(str(codex["environment"]))
    capture = "true" if codex.get("content_capture") else "false"
    return f"""#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
OUTPUT_DIR="$(cd "${{SCRIPT_DIR}}/.." && pwd)"
CAPTURE_CONTENT={capture}
JSONL_OUT="${{CODEX_O11Y_JSONL:-}}"
if [[ -z "${{JSONL_OUT}}" ]]; then
  JSONL_OUT="$(mktemp "${{TMPDIR:-/tmp}}/codex-o11y-exec.XXXXXX.jsonl")"
  chmod 600 "${{JSONL_OUT}}"
fi
SPAN_OUT="${{CODEX_O11Y_SPANS:-${{TMPDIR:-/tmp}}/codex-o11y-spans-$$.json}}"

# shellcheck disable=SC2329
cleanup_jsonl() {{
  if [[ "${{CAPTURE_CONTENT}}" != "true" && "${{CODEX_O11Y_KEEP_JSONL:-}}" != "true" ]]; then
    rm -f "${{JSONL_OUT}}"
  fi
}}
trap cleanup_jsonl EXIT

set +e
codex exec --json "$@" | tee "${{JSONL_OUT}}"
codex_rc=${{PIPESTATUS[0]}}
set -e

parser_args=(
  --input "${{JSONL_OUT}}"
  --output "${{SPAN_OUT}}"
  --service-name {service_name}
  --environment {environment}
)
if [[ "${{CAPTURE_CONTENT}}" == "true" ]]; then
  parser_args+=(--capture-content)
fi

if ! python3 "${{OUTPUT_DIR}}/bin/codex-o11y-jsonl-to-spans.py" "${{parser_args[@]}}"; then
  echo "WARN: Codex O11y JSONL parsing failed; leaving raw JSONL at ${{JSONL_OUT}}" >&2
fi

exit "${{codex_rc}}"
"""


def parse_codex_jsonl(
    text: str,
    *,
    source: str = "codex.exec",
    service_name: str = "codex-cli",
    environment: str = "prod",
    capture_content: bool = False,
    max_text_length: int = 256,
) -> dict[str, Any]:
    spans: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    current_thread = ""

    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {lineno}: invalid JSONL event: {exc.msg}")
            continue
        if not isinstance(event, dict):
            errors.append(f"line {lineno}: event is not an object")
            continue
        event_type = str(event.get("type", "unknown"))
        if event_type == "thread.started":
            current_thread = str(event.get("thread_id", ""))
        item = event.get("item") if isinstance(event.get("item"), dict) else {}
        event_id = str(item.get("id") or event.get("thread_id") or f"{lineno}:{event_type}")
        dedupe_key = f"{event_type}:{event_id}:{item.get('status', '')}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        attributes: dict[str, Any] = {
            "codex.event_type": event_type,
            "codex.source": source,
            "service.name": service_name,
            "deployment.environment": environment,
        }
        if current_thread:
            attributes["codex.thread_id"] = current_thread
        if item:
            attributes["codex.item_type"] = item.get("type", "")
            attributes["codex.item_status"] = item.get("status", "")
            if capture_content and isinstance(item.get("text"), str):
                text_value = item["text"]
                attributes["codex.content"] = text_value[:max_text_length]
                attributes["codex.content_truncated"] = len(text_value) > max_text_length
        spans.append(
            {
                "name": f"codex.{event_type}",
                "attributes": attributes,
                "metadata_only": not capture_content,
            }
        )
        usage = event.get("usage")
        if isinstance(usage, dict):
            for key, value in usage.items():
                if isinstance(value, int):
                    metrics.append(
                        {
                            "name": f"codex.usage.{key}",
                            "value": value,
                            "attributes": {
                                "codex.thread_id": current_thread,
                                "service.name": service_name,
                                "deployment.environment": environment,
                            },
                        }
                    )
    return {"spans": spans, "metrics": metrics, "errors": errors, "dedupe_count": len(seen)}


def render_jsonl_parser() -> str:
    return """#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def parse_jsonl(text, source, service_name, environment, capture_content=False, max_text_length=256):
    spans = []
    metrics = []
    errors = []
    seen = set()
    current_thread = ""
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {lineno}: invalid JSONL event: {exc.msg}")
            continue
        if not isinstance(event, dict):
            errors.append(f"line {lineno}: event is not an object")
            continue
        event_type = str(event.get("type", "unknown"))
        if event_type == "thread.started":
            current_thread = str(event.get("thread_id", ""))
        item = event.get("item") if isinstance(event.get("item"), dict) else {}
        event_id = str(item.get("id") or event.get("thread_id") or f"{lineno}:{event_type}")
        dedupe_key = f"{event_type}:{event_id}:{item.get('status', '')}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        attributes = {
            "codex.event_type": event_type,
            "codex.source": source,
            "service.name": service_name,
            "deployment.environment": environment,
        }
        if current_thread:
            attributes["codex.thread_id"] = current_thread
        if item:
            attributes["codex.item_type"] = item.get("type", "")
            attributes["codex.item_status"] = item.get("status", "")
            if capture_content and isinstance(item.get("text"), str):
                text_value = item["text"]
                attributes["codex.content"] = text_value[:max_text_length]
                attributes["codex.content_truncated"] = len(text_value) > max_text_length
        spans.append({"name": f"codex.{event_type}", "attributes": attributes, "metadata_only": not capture_content})
        usage = event.get("usage")
        if isinstance(usage, dict):
            for key, value in usage.items():
                if isinstance(value, int):
                    metrics.append({
                        "name": f"codex.usage.{key}",
                        "value": value,
                        "attributes": {
                            "codex.thread_id": current_thread,
                            "service.name": service_name,
                            "deployment.environment": environment,
                        },
                    })
    return {"spans": spans, "metrics": metrics, "errors": errors, "dedupe_count": len(seen)}


def main():
    parser = argparse.ArgumentParser(description="Convert Codex JSONL events into metadata-only span/metric JSON.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--source", default="codex.exec")
    parser.add_argument("--service-name", default="codex-cli")
    parser.add_argument("--environment", default="prod")
    parser.add_argument("--capture-content", action="store_true")
    args = parser.parse_args()
    text = Path(args.input).read_text(encoding="utf-8")
    payload = parse_jsonl(text, args.source, args.service_name, args.environment, args.capture_content)
    Path(args.output).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\\n", encoding="utf-8")
    if payload["errors"]:
        for error in payload["errors"]:
            print(error, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""


def render_stop_hook(config: dict[str, Any]) -> str:
    codex = config["codex"]
    capture = "true" if codex.get("content_capture") else "false"
    return f"""#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

CAPTURE_CONTENT = {capture == "true"}
SERVICE_NAME = {toml_quote(str(codex['service_name']))}
ENVIRONMENT = {toml_quote(str(codex['environment']))}


def log_failure(message: str) -> None:
    log_dir = Path(os.environ.get("CODEX_O11Y_HOOK_LOG_DIR", str(Path.home() / ".codex" / "o11y-logs")))
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "codex-o11y-stop-hook.log").open("a", encoding="utf-8") as handle:
        handle.write(message.rstrip() + "\\n")


def parse_jsonl(text: str) -> dict:
    spans = []
    seen = set()
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except Exception as exc:
            log_failure(f"line {{lineno}} parse failure: {{exc}}")
            continue
        event_type = str(event.get("type", "unknown"))
        item = event.get("item") if isinstance(event.get("item"), dict) else {{}}
        event_id = str(item.get("id") or event.get("thread_id") or f"{{lineno}}:{{event_type}}")
        if event_id in seen:
            continue
        seen.add(event_id)
        attrs = {{"codex.event_type": event_type, "service.name": SERVICE_NAME, "deployment.environment": ENVIRONMENT}}
        if CAPTURE_CONTENT and isinstance(item.get("text"), str):
            attrs["codex.content"] = item["text"][:256]
            attrs["codex.content_truncated"] = len(item["text"]) > 256
        spans.append({{"name": f"codex.interactive.{{event_type}}", "attributes": attrs, "metadata_only": not CAPTURE_CONTENT}})
    return {{"spans": spans, "dedupe_count": len(seen)}}


def main() -> int:
    try:
        hook_payload = {{}}
        try:
            stdin_text = "" if sys.stdin.isatty() else sys.stdin.read()
            if stdin_text.strip():
                loaded = json.loads(stdin_text)
                if isinstance(loaded, dict):
                    hook_payload = loaded
        except Exception as exc:
            log_failure(f"hook stdin parse failure: {{exc}}")
        session = (
            os.environ.get("CODEX_O11Y_SESSION_JSONL", "")
            or str(hook_payload.get("transcript_path") or hook_payload.get("transcriptPath") or "")
        )
        if not session:
            return 0
        path = Path(session).expanduser()
        if not path.exists():
            log_failure(f"session JSONL not found: {{path}}")
            return 0
        payload = parse_jsonl(path.read_text(encoding="utf-8"))
        out = Path(os.environ.get("CODEX_O11Y_INTERACTIVE_SPANS", str(path.with_suffix(".o11y-spans.json"))))
        out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\\n", encoding="utf-8")
    except Exception:
        log_failure(traceback.format_exc())
    return 0


if __name__ == "__main__":
    sys.exit(main())
"""


def hooks_json(hook_path: Path) -> dict[str, Any]:
    return {
        "hooks": {
            "Stop": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f'python3 "{hook_path}"',
                            "timeout": 30,
                            "statusMessage": MANAGED_HOOK_STATUS,
                        }
                    ]
                }
            ]
        }
    }


def apply_plan(config: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    codex = config["codex"]
    codex_home = resolve_codex_home(config)
    destination = str(codex["destination"])
    profiles = []
    for destination_name in destinations_for(destination):
        name = profile_name(destination_name, str(codex["profile_prefix"]))
        profiles.append(
            {
                "profile": name,
                "source": str(output_dir / "profiles" / f"{name}.config.toml"),
                "target": str(codex_home / f"{name}.config.toml"),
                "strict_config_command": ["codex", "--strict-config", "--profile", name],
            }
        )
    steps = [
        {
            "section": "profiles",
            "action": "copy user-level Codex profile config files",
            "commands": [["install", "-m", "0644", item["source"], item["target"]] for item in profiles],
        },
        {
            "section": "runtime",
            "action": "install Codex JSONL wrapper helpers",
            "commands": [
                ["install", "-m", "0755", str(output_dir / "bin" / "codex-o11y-exec"), str(codex_home / "bin" / "codex-o11y-exec")],
                [
                    "install",
                    "-m",
                    "0755",
                    str(output_dir / "bin" / "codex-o11y-jsonl-to-spans.py"),
                    str(codex_home / "bin" / "codex-o11y-jsonl-to-spans.py"),
                ],
            ],
        },
        {
            "section": "hooks",
            "action": "install optional user-level Stop hook and merge hooks.json; review and trust through /hooks before relying on it",
            "commands": [
                ["install", "-m", "0755", str(output_dir / "hooks" / "codex-o11y-stop-hook.py"), str(codex_home / "hooks" / "codex-o11y-stop-hook.py")],
                ["merge-hooks", str(output_dir / "hooks" / "hooks.json"), str(codex_home / "hooks.json")],
            ],
        },
        {
            "section": "env-helper",
            "action": "source shell env helper for token placeholders and helper paths",
            "commands": [["source", str(output_dir / "runtime" / "codex-o11y.env")]],
        },
    ]
    return {
        "generated_at": now_iso(),
        "skill": SKILL_NAME,
        "profiles": profiles,
        "steps": steps,
        "direct_secrets_rendered": False,
    }


def coverage_report(config: dict[str, Any]) -> dict[str, Any]:
    codex = config["codex"]
    destination = str(codex["destination"])
    entries = [
        {
            "key": "codex.user_profiles",
            "status": "render",
            "summary": "Codex OTel belongs in user-level CODEX_HOME profile files, not project .codex/config.toml.",
            "source_url": "https://developers.openai.com/codex/codex-manual.md",
        },
        {
            "key": "codex.strict_config",
            "status": "validate",
            "summary": "codex --strict-config --profile validates Codex config shape; endpoint semantics are validated by this skill.",
            "source_url": "https://developers.openai.com/codex/codex-manual.md",
        },
        {
            "key": "splunk.direct_otlp_http",
            "status": "render" if destination in {"direct", "all"} else "not_applicable",
            "summary": "Direct Splunk ingest renders OTLP/HTTP traces and metrics only.",
            "source_url": "https://dev.splunk.com/observability/reference/api/ingest_data/latest",
        },
        {
            "key": "splunk.collector_logs",
            "status": "render" if codex.get("enable_native_logs") else "not_applicable",
            "summary": "Native Codex logs are allowed only through local or external collector destinations.",
            "source_url": "https://developers.openai.com/codex/codex-manual.md",
        },
        {
            "key": "splunk.histograms",
            "status": "render",
            "summary": "Collector overlay sets send_otlp_histograms: true.",
            "source_url": "https://help.splunk.com/en/splunk-observability-cloud/manage-data/metrics-metadata-and-events/metrics-events-and-metadata/get-histogram-data-in",
        },
        {
            "key": "advanced_genai_spans",
            "status": "render" if codex.get("enable_advanced_genai_spans") else "render_disabled",
            "summary": "codex-o11y-exec wraps codex exec --json and converts JSONL events into metadata-only spans and metrics by default.",
            "source_url": "https://developers.openai.com/codex/codex-manual.md",
        },
        {
            "key": "ai_defense",
            "status": "render" if codex.get("enable_ai_defense") else "not_applicable",
            "summary": "AI Defense content inspection is gated behind an explicit acceptance flag.",
            "source_url": "https://help.splunk.com/en/splunk-observability-cloud/observability-for-ai/splunk-ai-agent-monitoring/set-up-ai-agent-monitoring/code-based-instrumentation",
        },
    ]
    return {"generated_at": now_iso(), "coverage": entries}


def doctor_report(config: dict[str, Any], errors: list[str], warnings: list[str]) -> str:
    codex = config["codex"]
    lines = [
        "# Codex O11y Doctor Report",
        "",
        f"Generated: `{now_iso()}`",
        "",
        "## Destination",
        "",
        f"- Selected destination: `{codex['destination']}`",
        f"- Native logs enabled: `{str(bool(codex.get('enable_native_logs'))).lower()}`",
        f"- Advanced GenAI spans enabled: `{str(bool(codex.get('enable_advanced_genai_spans'))).lower()}`",
        f"- Content capture enabled: `{str(bool(codex.get('content_capture'))).lower()}`",
        f"- AI Defense enabled: `{str(bool(codex.get('enable_ai_defense'))).lower()}`",
        "",
        "## Findings",
        "",
    ]
    if not errors and not warnings:
        lines.append("- OK: render contract is valid.")
    for error in errors:
        lines.append(f"- ERROR: {error}")
    for warning in warnings:
        lines.append(f"- WARN: {warning}")
    lines.extend(
        [
            "",
            "## Operator Checks",
            "",
            "- Run the rendered strict-config commands from `apply-plan.json` after copying profiles into `CODEX_HOME`.",
            "- Use `/hooks` to review and trust the optional Stop hook before relying on interactive session capture.",
            "- Confirm Splunk endpoint reachability with a collector or separate OTLP smoke tool; `codex --strict-config` does not validate Splunk ingest semantics.",
        ]
    )
    return "\n".join(lines) + "\n"


def render_runtime_env(config: dict[str, Any], output_dir: Path) -> str:
    codex = config["codex"]
    capture = "true" if codex.get("content_capture") else "false"
    return f"""# Source this file before running Codex O11y helpers.
export CODEX_O11Y_RENDERED_DIR={shell_quote(output_dir)}
export CODEX_O11Y_SERVICE_NAME={shell_quote(codex['service_name'])}
export CODEX_O11Y_ENVIRONMENT={shell_quote(codex['environment'])}
export CODEX_O11Y_CAPTURE_CONTENT={shell_quote(capture)}
# Direct Splunk profiles expect SPLUNK_ACCESS_TOKEN in the runtime environment.
# Do not place token values in this file.
"""


def render_galileo_notify_handoff(config: dict[str, Any]) -> str:
    codex = config["codex"]
    return f"""# Codex Notify to Galileo Handoff

This handoff captures the proven path for sending completed Codex turns into a
Galileo Observe log stream. It is separate from Codex native `[otel]` profile
export and from the Galileo MCP server.

## Key Behavior

- A configured Galileo MCP server gives Codex access to Galileo tools, but it
  does not automatically subscribe to or mirror Codex turns.
- Codex native `[otel]` profile export is controlled by the active Codex
  profile. If `[otel].exporter = "none"`, native Codex log export is disabled;
  a `notify` command can still run at turn end.
- The practical interactive path is a fail-soft `notify` wrapper that runs on
  `turn-ended`, parses the local session JSONL under `CODEX_HOME/sessions`, and
  logs one Galileo trace per completed turn.
- Use Galileo direct trace ingest for this bridge:
  `POST /v2/projects/{{project_id}}/traces`.
- Set `reliable=true` and `include_trace_ids=true` so the notifier can log
  non-secret acknowledgement evidence.
- Verify storage, not only ingest acceptance, with:
  `POST /v2/projects/{{project_id}}/traces/count` and
  `POST /v2/projects/{{project_id}}/export_records`.
- Galileo `user_metadata` values must be strings. Convert counts and booleans
  before sending them.

## Recommended Trace Shape

- Trace name: `codex.turn`
- Tags: `codex`, `codex-cli`, `turn-ended`
- User metadata: `turn_id`, `session_id`, `event`, `model`,
  `collaboration_mode`, `host`, `session_file`, `tool_count`,
  `retrieval_count`
- One LLM child span for the turn summary
- Tool child spans for terminal, patch, MCP, browser, or other tool calls
- Retriever child spans for web-search events when present

## Secret And Content Guardrails

- Read the Galileo API key from a file such as `GALILEO_API_KEY_FILE`; never
  pass the key on argv.
- Keep the notifier fail-soft: local failures should write a log and exit `0`
  so telemetry cannot block Codex.
- Keep a local emitted-turn state file to avoid duplicate turn export. A common
  path is `CODEX_HOME/log/codex-galileo-emitted-turns.json`.
- Log non-secret local failures to a separate file, for example
  `CODEX_HOME/log/codex-galileo-notify.log`.
- Redact obvious secrets, bearer tokens, JWTs, and high-entropy strings before
  sending content to Galileo.
- Prompt, response, tool argument, and tool output capture is data capture. Use
  metadata-only placeholders unless the operator explicitly accepts content
  capture.

## Local Verification Pattern

After a turn completes, the notifier should print or log non-secret evidence
similar to:

```json
{{
  "ok": true,
  "turn_id": "019f...",
  "trace_id": "uuid",
  "galileo_trace_ids": ["uuid"],
  "records_count": 22,
  "spans_count": 21
}}
```

Then verify by filtering on the returned trace ID through `traces/count` and
`export_records`. A stored turn should export as a `codex.turn` trace with
`event=turn-ended`.

## Splunk O11y Relationship

This skill still renders Splunk Observability profiles, collector overlays, and
JSONL helpers for `{codex.get("service_name", "codex-cli")}`. The Galileo
notify bridge is a companion handoff for Galileo Observe; it does not replace
the Splunk OTel profile or collector path.
"""


def render_handoff(config: dict[str, Any], output_dir: Path) -> str:
    codex = config["codex"]
    lines = [
        "# Codex O11y Handoff",
        "",
        "## Profile Install",
        "",
        "Copy selected `profiles/*.config.toml` files into `CODEX_HOME`, then run the matching strict-config command from `apply-plan.json`.",
        "",
        "## Hook Trust",
        "",
        "The optional Stop hook is a user-level hook. Start Codex and run `/hooks` to review and trust it before relying on interactive session capture.",
        "",
        "## Direct Mode",
        "",
        "Direct mode sends traces and metrics only through OTLP/HTTP endpoints. Native Codex log export remains disabled.",
        "",
        "## Advanced Spans",
        "",
        f"Use `{output_dir / 'bin' / 'codex-o11y-exec'}` for `codex exec --json` metadata capture.",
        f"Content capture is `{str(bool(codex.get('content_capture'))).lower()}`.",
        "",
        "## Galileo Notify Bridge",
        "",
        "Review `runtime/codex-notify-galileo-handoff.md` when Codex turns must appear in a Galileo Observe log stream. Galileo MCP connectivity alone does not emit Codex turns.",
    ]
    return "\n".join(lines) + "\n"


def render(config: dict[str, Any], output_dir: Path, json_output: bool = False) -> dict[str, Any]:
    errors, warnings = validate_config(config)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Remove only files owned by this renderer when re-rendering.
    for child in ("profiles", "collector", "runtime", "bin", "hooks"):
        target = output_dir / child
        if target.exists():
            shutil.rmtree(target)

    if errors:
        metadata = {"ok": False, "errors": errors, "warnings": warnings, "generated_at": now_iso()}
        write_json(output_dir / "metadata.json", metadata)
        write_text(output_dir / "doctor-report.md", doctor_report(config, errors, warnings))
        if json_output:
            print(json.dumps(metadata, indent=2, sort_keys=True))
        raise UsageError("; ".join(errors))

    codex = config["codex"]
    prefix = str(codex["profile_prefix"])
    rendered_profiles: list[str] = []
    for destination in destinations_for(str(codex["destination"])):
        name = profile_name(destination, prefix)
        path = output_dir / "profiles" / f"{name}.config.toml"
        if destination == "local-collector":
            text = local_profile(config)
        elif destination == "external-collector":
            text = external_profile(config)
        else:
            text = direct_profile(config)
        write_text(path, text)
        validate_toml_file(path)
        rendered_profiles.append(path.relative_to(output_dir).as_posix())

    write_text(output_dir / "collector" / "codex-o11y-local-collector.yaml", render_collector_overlay(config))
    write_text(output_dir / "bin" / "codex-o11y-exec", render_exec_wrapper(config), executable=True)
    write_text(output_dir / "bin" / "codex-o11y-jsonl-to-spans.py", render_jsonl_parser(), executable=True)
    write_text(output_dir / "hooks" / "codex-o11y-stop-hook.py", render_stop_hook(config), executable=True)
    write_json(
        output_dir / "hooks" / "hooks.json",
        hooks_json(resolve_codex_home(config) / "hooks" / "codex-o11y-stop-hook.py"),
    )
    write_text(output_dir / "runtime" / "codex-o11y.env", render_runtime_env(config, output_dir))
    write_text(output_dir / "runtime" / "codex-notify-galileo-handoff.md", render_galileo_notify_handoff(config))

    plan = apply_plan(config, output_dir)
    coverage = coverage_report(config)
    write_json(output_dir / "apply-plan.json", plan)
    write_json(output_dir / "coverage-report.json", coverage)
    write_text(output_dir / "coverage-report.md", coverage_markdown(coverage))
    write_text(output_dir / "doctor-report.md", doctor_report(config, errors, warnings))
    write_text(output_dir / "handoff.md", render_handoff(config, output_dir))

    leak_errors = scan_rendered_for_secret_leaks(output_dir)
    metadata = {
        "ok": not leak_errors,
        "skill": SKILL_NAME,
        "generated_at": now_iso(),
        "output_dir": str(output_dir),
        "rendered_profiles": rendered_profiles,
        "destination": codex["destination"],
        "strict_config_commands": [profile["strict_config_command"] for profile in plan["profiles"]],
        "direct_secrets_rendered": False,
        "errors": leak_errors,
        "warnings": warnings,
    }
    write_json(output_dir / "metadata.json", metadata)
    if leak_errors:
        raise UsageError("; ".join(leak_errors))
    return metadata


def coverage_markdown(coverage: dict[str, Any]) -> str:
    lines = ["# Coverage Report", "", "| Key | Status | Summary |", "|---|---|---|"]
    for entry in coverage.get("coverage", []):
        lines.append(f"| `{entry['key']}` | `{entry['status']}` | {entry['summary']} |")
    return "\n".join(lines) + "\n"


def validate_output(output_dir: Path, json_output: bool = False) -> dict[str, Any]:
    required = [
        "metadata.json",
        "apply-plan.json",
        "coverage-report.json",
        "coverage-report.md",
        "doctor-report.md",
        "handoff.md",
        "collector/codex-o11y-local-collector.yaml",
        "runtime/codex-o11y.env",
        "runtime/codex-notify-galileo-handoff.md",
        "bin/codex-o11y-exec",
        "bin/codex-o11y-jsonl-to-spans.py",
        "hooks/hooks.json",
        "hooks/codex-o11y-stop-hook.py",
    ]
    errors: list[str] = []
    warnings: list[str] = []
    for rel in required:
        path = output_dir / rel
        if not path.exists():
            errors.append(f"missing rendered artifact: {rel}")
        elif path.is_file() and path.stat().st_size == 0:
            errors.append(f"empty rendered artifact: {rel}")

    profiles_dir = output_dir / "profiles"
    profiles = sorted(profiles_dir.glob("*.config.toml")) if profiles_dir.exists() else []
    if not profiles:
        errors.append("no profile config TOML files rendered")
    for profile in profiles:
        try:
            validate_toml_file(profile)
        except Exception as exc:
            errors.append(f"{profile.name}: invalid TOML: {exc}")
        text = profile.read_text(encoding="utf-8")
        if profile.name.endswith("direct.config.toml"):
            if 'exporter = "none"' not in text:
                errors.append("direct profile must keep native log exporter disabled")
            if "otlp-grpc" in text:
                errors.append("direct profile must not render otlp-grpc")
            if "/v2/trace/otlp" not in text or "/v2/datapoint/otlp" not in text:
                errors.append("direct profile missing Splunk OTLP trace or metric endpoints")
            if '"X-SF-TOKEN" = "${SPLUNK_ACCESS_TOKEN}"' not in text:
                errors.append("direct profile missing safe X-SF-TOKEN environment placeholder")
        if profile.name.endswith("local.config.toml") and (
            "/v1/traces" not in text or "/v1/metrics" not in text
        ):
            errors.append("local profile missing local collector trace or metric endpoints")

    if (output_dir / "collector/codex-o11y-local-collector.yaml").exists():
        values = (output_dir / "collector/codex-o11y-local-collector.yaml").read_text(encoding="utf-8")
        if "send_otlp_histograms: true" not in values:
            errors.append("collector overlay must set send_otlp_histograms: true")

    if (output_dir / "hooks/hooks.json").exists():
        try:
            hooks = json.loads((output_dir / "hooks/hooks.json").read_text(encoding="utf-8"))
            if "Stop" not in hooks.get("hooks", {}):
                errors.append("hooks.json missing Stop hook")
        except json.JSONDecodeError as exc:
            errors.append(f"hooks.json invalid JSON: {exc}")

    if (output_dir / "apply-plan.json").exists():
        plan = json.loads((output_dir / "apply-plan.json").read_text(encoding="utf-8"))
        joined = json.dumps(plan)
        if "codex --strict-config --profile" not in " ".join(
            " ".join(profile.get("strict_config_command", [])) for profile in plan.get("profiles", [])
        ):
            errors.append("apply-plan.json missing codex --strict-config --profile command")
        for forbidden in (" --token ", " --access-token ", " --sf-token ", " --o11y-token ", " --api-key ", " --password "):
            if forbidden in f" {joined} ":
                errors.append(f"apply-plan.json contains forbidden direct-secret flag: {forbidden.strip()}")
        runtime_commands = [
            command
            for step in plan.get("steps", [])
            if step.get("section") == "runtime"
            for command in step.get("commands", [])
        ]
        if not any(command and str(command[-1]).endswith("codex-o11y-jsonl-to-spans.py") for command in runtime_commands):
            errors.append("apply-plan.json runtime section must install codex-o11y-jsonl-to-spans.py")
        hook_commands = [
            command
            for step in plan.get("steps", [])
            if step.get("section") == "hooks"
            for command in step.get("commands", [])
        ]
        if not any(command and command[0] == "merge-hooks" for command in hook_commands):
            errors.append("apply-plan.json hooks section must merge hooks.json instead of overwriting it")

    errors.extend(scan_rendered_for_secret_leaks(output_dir))
    metadata = {}
    if (output_dir / "metadata.json").exists():
        metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
        errors.extend(metadata.get("errors", []))
        warnings.extend(metadata.get("warnings", []))
    payload = {"ok": not errors, "errors": errors, "warnings": warnings, "output_dir": str(output_dir)}
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        if errors:
            print("Validation failed:", file=sys.stderr)
            for error in errors:
                print(f"  - {error}", file=sys.stderr)
        else:
            print(f"validate: OK -> {output_dir}")
    if errors:
        raise SystemExit(1)
    return payload


def merge_hooks_file(source: Path, target: Path) -> None:
    source_doc = json.loads(source.read_text(encoding="utf-8"))
    managed_stop = source_doc.get("hooks", {}).get("Stop")
    if not isinstance(managed_stop, list) or not managed_stop:
        raise UsageError("rendered hooks.json does not contain a Stop hook")

    if target.exists():
        target_doc = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(target_doc, dict):
            raise UsageError(f"existing hooks file is not a JSON object: {target}")
    else:
        target_doc = {}

    hooks = target_doc.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise UsageError(f"existing hooks root is not a JSON object: {target}")
    stop_hooks = hooks.setdefault("Stop", [])
    if not isinstance(stop_hooks, list):
        raise UsageError(f"existing Stop hooks entry is not a list: {target}")

    def is_managed_stop(entry: Any) -> bool:
        if not isinstance(entry, dict):
            return False
        for hook in entry.get("hooks", []):
            if isinstance(hook, dict) and hook.get("statusMessage") == MANAGED_HOOK_STATUS:
                return True
        return False

    hooks["Stop"] = [entry for entry in stop_hooks if not is_managed_stop(entry)]
    hooks["Stop"].extend(managed_stop)
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json(target, target_doc)


def apply_sections(config: dict[str, Any], output_dir: Path, sections: list[str], dry_run: bool, json_output: bool) -> dict[str, Any]:
    plan_path = output_dir / "apply-plan.json"
    metadata_path = output_dir / "metadata.json"
    if plan_path.exists():
        validate_output(output_dir, json_output=False)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    else:
        metadata = render(config, output_dir, json_output=False)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    selected = list(APPLY_SECTIONS) if sections == ["all"] else sections
    unknown = sorted(set(selected) - set(APPLY_SECTIONS))
    if unknown:
        raise UsageError(f"unknown apply section(s): {', '.join(unknown)}")
    operations: list[dict[str, Any]] = []
    for step in plan["steps"]:
        if step["section"] not in selected:
            continue
        for command in step["commands"]:
            operations.append({"section": step["section"], "command": command})
            if dry_run:
                continue
            if command[0] == "source":
                continue
            if command[0] == "install":
                target = Path(os.path.expandvars(os.path.expanduser(command[-1])))
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(command[-2], target)
                if command[2] == "0755":
                    target.chmod(target.stat().st_mode | 0o111)
            elif command[0] == "merge-hooks":
                merge_hooks_file(Path(command[1]), Path(os.path.expandvars(os.path.expanduser(command[2]))))
            else:
                subprocess.run(command, check=True)
    payload = {
        "ok": True,
        "dry_run": dry_run,
        "metadata": metadata,
        "operations": operations,
    }
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for operation in operations:
            prefix = "DRY RUN:" if dry_run else "APPLIED:"
            print(f"{prefix} [{operation['section']}] {shell_join(operation['command'])}")
    return payload


def discover(json_output: bool) -> dict[str, Any]:
    payload = {
        "agents": ["codex"],
        "destinations": sorted(VALID_DESTINATIONS),
        "protocols": sorted(VALID_PROTOCOLS),
        "apply_sections": list(APPLY_SECTIONS) + ["all"],
        "sources": [
            "https://developers.openai.com/codex/codex-manual.md",
            "https://dev.splunk.com/observability/reference/api/ingest_data/latest",
            "https://help.splunk.com/en/splunk-observability-cloud/observability-for-ai/splunk-ai-agent-monitoring/set-up-ai-agent-monitoring/code-based-instrumentation",
        ],
    }
    print_payload(payload, json_output)
    return payload


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--render", action="store_true")
    modes.add_argument("--validate", action="store_true")
    modes.add_argument("--doctor", action="store_true")
    modes.add_argument("--discover", action="store_true")
    modes.add_argument("--apply", nargs="?", const="all", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--spec")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--codex-home", default="")
    parser.add_argument("--environment", default="")
    parser.add_argument("--service-name", default="")
    parser.add_argument("--realm", default="")
    parser.add_argument("--destination", choices=sorted(VALID_DESTINATIONS), default="")
    parser.add_argument("--local-collector-endpoint", default="")
    parser.add_argument("--external-trace-endpoint", default="")
    parser.add_argument("--external-metric-endpoint", default="")
    parser.add_argument("--external-log-endpoint", default="")
    parser.add_argument("--external-collector-protocol", choices=sorted(VALID_PROTOCOLS), default="")
    parser.add_argument("--external-header", action="append", default=[])
    parser.add_argument("--external-ca-certificate", default="")
    parser.add_argument("--external-client-certificate", default="")
    parser.add_argument("--external-client-private-key", default="")
    parser.add_argument("--enable-native-logs", action="store_true")
    parser.add_argument("--enable-advanced-genai-spans", action="store_true")
    parser.add_argument("--accept-content-capture", action="store_true")
    parser.add_argument("--enable-ai-defense", action="store_true")
    parser.add_argument("--accept-ai-defense-content-inspection", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    json_output = "--json" in argv
    try:
        reject_secret_argv(argv)
        args = parse_args(argv)
        output_dir = Path(args.output_dir).expanduser().resolve()
        if args.discover:
            discover(args.json)
            return 0
        config = load_spec_with_args(args)
        if args.validate:
            validate_output(output_dir, args.json)
            return 0
        if args.doctor:
            metadata = render(config, output_dir, json_output=False)
            if args.json:
                print(json.dumps(metadata, indent=2, sort_keys=True))
            else:
                print((output_dir / "doctor-report.md").read_text(encoding="utf-8"))
            return 0
        if args.apply:
            sections = split_csv(args.apply)
            if not sections:
                sections = ["all"]
            apply_sections(config, output_dir, sections, args.dry_run, args.json)
            return 0
        metadata = render(config, output_dir, json_output=False)
        if args.json:
            print(json.dumps(metadata, indent=2, sort_keys=True))
        else:
            print(f"rendered Codex O11y assets -> {output_dir}")
        return 0
    except SystemExit:
        raise
    except Exception as exc:
        return command_failed(exc, json_output)


if __name__ == "__main__":
    raise SystemExit(main())
