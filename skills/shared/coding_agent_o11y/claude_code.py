#!/usr/bin/env python3
"""Render and validate Splunk Observability instrumentation for Claude Code."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import SplitResult, quote, urlsplit

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
    write_json,
    write_text,
)


SKILL_NAME = "splunk-observability-claude-code-instrumentation-setup"
API_VERSION = f"{SKILL_NAME}/v1"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "splunk-observability-claude-code-instrumentation-rendered"
VALID_DESTINATIONS = {"local-collector", "external-collector", "splunk-direct", "all"}
VALID_SCOPES = {"user", "project", "managed"}
VALID_PROTOCOLS = {"grpc", "http/json", "http/protobuf"}
VALID_TEMPORALITY_PREFERENCES = {"cumulative", "delta"}
PROTOCOL_ALIASES = {"otlp-http": "http/protobuf", "otlp-grpc": "grpc"}
VALID_PROTOCOL_INPUTS = VALID_PROTOCOLS | set(PROTOCOL_ALIASES)
APPLY_SECTIONS = ("settings", "env-helper", "collector-overlay", "galileo-handoff")
MANAGED_SETTINGS_MARKER = "splunk-observability-claude-code-instrumentation-setup"
DEFAULT_GALILEO_OTEL_ENDPOINT = "https://api.galileo.ai/otel/traces"
GENAI_TOKEN_HISTOGRAM_CONNECTOR = "signal_to_metrics/claude_code_token_histogram"
MIN_ASSISTANT_RESPONSE_VERSION = (2, 1, 193)
GALILEO_OUTPUT_SCRATCH_ATTRIBUTE = "_claude_code.galileo.final_output"
GALILEO_CODING_AGENT_METRICS = (
    "action_completion_luna",
    "completeness_luna",
    "action_advancement_luna",
    "tool_selection_quality_luna",
    "tool_error_rate_luna",
)
GENAI_TOKEN_HISTOGRAM_BUCKETS = (
    1,
    4,
    16,
    64,
    256,
    1024,
    4096,
    16384,
    65536,
    262144,
    1048576,
    4194304,
    16777216,
    67108864,
)

MANAGED_ENV_PREFIXES = ("CLAUDE_CODE_", "OTEL_")
# Managed env keys that do not share the CLAUDE_CODE_/OTEL_ prefixes but are still
# owned by this skill (detailed beta tracing). Tracked explicitly so merge_settings_file
# strips stale values when the operator switches destinations or disables detailed traces.
MANAGED_ENV_EXACT = (
    "ENABLE_BETA_TRACING_DETAILED",
    "BETA_TRACING_ENDPOINT",
    "NODE_EXTRA_CA_CERTS",
)
MANAGED_TOP_LEVEL_KEYS = ("otelHeadersHelper",)


def is_managed_env_key(key: str) -> bool:
    return key in MANAGED_ENV_EXACT or any(key.startswith(prefix) for prefix in MANAGED_ENV_PREFIXES)


DEFAULT_SPEC: dict[str, Any] = {
    "api_version": API_VERSION,
    "claude_code": {
        "settings_scope": "user",
        "environment": "prod",
        "service_name": "claude-code",
        "realm": "us0",
        "destination": "local-collector",
        "enable_traces_beta": True,
        # Detailed beta tracing adds hook spans and experimental attributes on
        # current Claude Code releases. It requires ENABLE_BETA_TRACING_DETAILED=1
        # plus a BETA_TRACING_ENDPOINT separate from the standard trace endpoint.
        "enable_detailed_traces": False,
        "galileo_enabled": False,
        "galileo_console_url": "",
        "galileo_project": "",
        "galileo_log_stream": "default",
        # Intentionally blank: every Galileo-enabled workflow must receive the
        # user's instance URL instead of silently assuming the public tenant.
        "galileo_otel_endpoint": "",
        "local_collector_endpoint": "http://127.0.0.1:14318",
        "collector_receiver_endpoint": "",
        "external_collector_endpoint": "",
        "metric_export_interval_ms": 60000,
        "logs_export_interval_ms": 5000,
        "traces_export_interval_ms": 5000,
        "metrics_include_session_id": True,
        "metrics_include_version": False,
        "metrics_include_account_uuid": True,
        "metrics_include_entrypoint": False,
        "metrics_include_resource_attributes": True,
        "metrics_temporality_preference": "delta",
        "log_user_prompts": False,
        "log_assistant_responses": False,
        "log_tool_details": False,
        "log_tool_content": False,
        "log_raw_api_bodies": "",
        "accept_content_capture": False,
        "provider_name": "",
        "model_aliases": {},
        "external_collector_protocol": "http/protobuf",
        "external_trace_endpoint": "",
        "external_metric_endpoint": "",
        "external_log_endpoint": "",
        "external_headers": {},
        "external_tls": {},
        "resource_attributes": {},
    },
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def yaml_quote(value: str) -> str:
    return json.dumps(str(value))


def shell_quote(value: object) -> str:
    return shlex.quote(str(value))


def destinations_for(value: str) -> list[str]:
    return ["local-collector", "splunk-direct"] if value == "all" else [value]


def bool_config(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def parse_claude_code_version(value: str) -> tuple[int, int, int] | None:
    match = re.search(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)", value)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def require_assistant_response_capable_claude() -> tuple[int, int, int]:
    """Fail closed before applying response capture to an unsupported CLI.

    Claude Code added the ``assistant_response`` OTel event in v2.1.193. Older
    binaries accept the environment variable but emit no response text, which
    looks like a healthy pipeline with permanently blank Galileo output.
    """
    executable = shutil.which("claude")
    if not executable:
        raise UsageError(
            "assistant response capture requires Claude Code v2.1.193 or newer, "
            "but no claude executable was found"
        )
    completed = subprocess.run(
        [executable, "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    version = parse_claude_code_version(completed.stdout + "\n" + completed.stderr)
    if completed.returncode != 0 or version is None:
        raise UsageError(
            "could not determine Claude Code version before enabling assistant response capture"
        )
    if version < MIN_ASSISTANT_RESPONSE_VERSION:
        current = ".".join(str(part) for part in version)
        minimum = ".".join(str(part) for part in MIN_ASSISTANT_RESPONSE_VERSION)
        raise UsageError(
            f"assistant response capture requires Claude Code v{minimum} or newer; "
            f"found v{current}. Homebrew stable can lag; install claude-code@latest "
            "or use Anthropic's native installer."
        )
    return version


def normalize_protocol(value: object) -> str:
    raw = str(value or "http/protobuf").strip()
    return PROTOCOL_ALIASES.get(raw, raw)


def parse_local_collector_endpoint(value: object) -> SplitResult:
    raw = str(value or "").strip()
    if not raw:
        raise UsageError("local_collector_endpoint is required")
    parsed = urlsplit(raw)
    if parsed.scheme != "http":
        raise UsageError(
            "local_collector_endpoint must use http:// because the rendered local collector receiver is plain OTLP HTTP"
        )
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


def normalize_collector_receiver_endpoint(value: object, client_endpoint: object) -> str:
    """Return the collector's bind address.

    Host-native collectors normally bind to the same host/port that Claude uses.
    Docker deployments need a distinct container-side bind such as
    ``0.0.0.0:4318`` while Claude still connects to ``127.0.0.1:14318``.
    """
    raw = str(value or "").strip()
    if not raw:
        return local_collector_receiver_endpoint(client_endpoint)
    if "://" in raw or "/" in raw:
        raise UsageError(
            "collector_receiver_endpoint must be a bind address such as 0.0.0.0:4318, without a URL scheme or path"
        )
    parsed = urlsplit(f"//{raw}")
    if not parsed.hostname or parsed.username or parsed.password:
        raise UsageError("collector_receiver_endpoint must include a host and must not include credentials")
    try:
        port = parsed.port
    except ValueError as exc:
        raise UsageError(f"collector_receiver_endpoint has an invalid port: {exc}") from exc
    if port is None:
        raise UsageError("collector_receiver_endpoint must include an explicit port")
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{host}:{port}"


def parse_galileo_endpoint(value: object) -> SplitResult:
    raw = str(value or "").strip()
    if not raw:
        raise UsageError("galileo_otel_endpoint is required when Galileo is enabled")
    parsed = urlsplit(raw)
    if parsed.scheme != "https":
        raise UsageError("galileo_otel_endpoint must use https://")
    if not parsed.hostname:
        raise UsageError("galileo_otel_endpoint must include a host")
    if parsed.username or parsed.password:
        raise UsageError("galileo_otel_endpoint must not include credentials")
    if parsed.query or parsed.fragment:
        raise UsageError("galileo_otel_endpoint must not include a query string or fragment")
    if not (parsed.path.endswith("/otel/traces") or parsed.path.endswith("/otel/v1/traces")):
        raise UsageError("galileo_otel_endpoint must end with /otel/traces or /otel/v1/traces")
    return parsed


def galileo_endpoint_from_console(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise UsageError("galileo console URL must be https:// with a host")
    if parsed.username or parsed.password:
        raise UsageError("galileo console URL must not include credentials")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise UsageError("galileo console URL must contain only the instance origin, without a path, query, or fragment")
    host = parsed.hostname.lower()
    # Galileo documents both console.<domain> -> api.<domain> and
    # console-<name>.<domain> -> api-<name>.<domain>. Public Galileo Cloud uses
    # app.galileo.ai rather than the console prefix.
    if host == "app.galileo.ai":
        host = "api.galileo.ai"
    elif host.startswith("console."):
        host = "api." + host[len("console.") :]
    elif host.startswith("console-"):
        host = "api-" + host[len("console-") :]
    elif host.startswith("api.") or host.startswith("api-"):
        pass
    else:
        raise UsageError(
            "galileo console URL must be https://app.galileo.ai or use a documented "
            "console./console- host so the corresponding api./api- endpoint can be derived; "
            "otherwise pass the full endpoint with --galileo-otel-endpoint"
        )
    try:
        port = parsed.port
    except ValueError as exc:
        raise UsageError(f"galileo console URL has an invalid port: {exc}") from exc
    if port:
        host = f"{host}:{parsed.port}"
    return f"https://{host}/otel/traces"


REALM_RE = re.compile(r"^[a-z0-9]+$")
SAFE_TLS_VALUE_RE = re.compile(
    r"^(?:\$\{[A-Za-z_][A-Za-z0-9_]*\}|[A-Za-z0-9./~][A-Za-z0-9 ._:/@=~+-]{0,180})$"
)
ENV_PLACEHOLDER_LOCAL_RE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*\}$")
RESOURCE_ATTRIBUTE_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,127}$")
GALILEO_CREDENTIAL_LIKE_RE = re.compile(
    r"(?i)^(?:bearer\s+|basic\s+|sk-[A-Za-z0-9_-]{12,}|"
    r"gai[-_][A-Za-z0-9_-]{12,}|galileo[-_](?:api[-_])?key[-_][A-Za-z0-9_-]{8,}|"
    r"eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,})"
)


def validate_realm(value: object) -> str:
    """Validate a Splunk Observability realm token. Realms are lowercase
    alphanumeric (us0, us1, eu0, jp0, au0). Rejecting anything else prevents
    path/quote injection into the rendered ingest URLs."""
    realm = str(value or "").strip()
    if not realm:
        raise UsageError("realm is required")
    if not REALM_RE.match(realm):
        raise UsageError("realm must be lowercase alphanumeric (for example us1, eu0)")
    return realm


def ensure_safe_external_tls_value(label: str, value: str) -> None:
    if not value:
        return
    if re.search(r"(?i)(?:token|password|api[_-]?key|secret|access[_-]?token)\s*=", value):
        raise UsageError(f"{label} looks like an inline secret assignment; use an environment placeholder.")
    if not SAFE_TLS_VALUE_RE.fullmatch(value):
        raise UsageError(f"{label} must be a safe file path or an environment placeholder.")


def ensure_safe_galileo_route_value(label: str, value: str) -> None:
    """Project and log-stream values are identifiers, not credentials.

    Accept long UUIDs/slugs used by Galileo tenants while still rejecting obvious
    credential material such as bearer strings, JWTs, and API-key-looking values.
    """
    if not value:
        return
    if ENV_PLACEHOLDER_LOCAL_RE.fullmatch(value):
        return
    ensure_safe_external_value(label, value, reject_token_like=False)
    if GALILEO_CREDENTIAL_LIKE_RE.search(value):
        raise UsageError(f"{label} looks like credential material; use a Galileo project or log-stream identifier.")


def encode_resource_attribute_value(value: object) -> str:
    """Encode values for OTEL_RESOURCE_ATTRIBUTES' comma-delimited grammar."""
    # Claude Code follows the OTel env grammar: whitespace, quotes, commas,
    # semicolons, backslashes, and non-ASCII bytes must be percent encoded.
    return quote(str(value), safe="!#$%&'()*+-./:<=>?@[]^_`{|}~")


def parse_model_alias(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise UsageError("--model-alias must use SOURCE_MODEL=DISPLAY_MODEL")
    source, target = (part.strip() for part in value.split("=", 1))
    if not source or not target:
        raise UsageError("--model-alias requires non-empty source and display model values")
    ensure_safe_external_value("model alias source", source)
    ensure_safe_external_value("model alias target", target)
    return source, target


def normalize_raw_api_bodies(value: object) -> str:
    if value in (None, "", False, 0, "0", "false"):
        return ""
    if value is True or str(value).strip() == "1":
        return "1"
    raw = str(value).strip()
    if not raw.startswith("file:"):
        raise UsageError("log_raw_api_bodies must be '1' or file:/absolute/directory")
    directory = Path(raw[len("file:") :]).expanduser()
    if not directory.is_absolute():
        raise UsageError("log_raw_api_bodies file mode requires an absolute directory")
    return f"file:{directory}"


def external_dynamic_headers(config: dict[str, Any]) -> dict[str, str]:
    headers = config["claude_code"].get("external_headers") or {}
    if not isinstance(headers, dict):
        return {}
    dynamic: dict[str, str] = {}
    for key, value in headers.items():
        rendered = str(value)
        if ENV_PLACEHOLDER_LOCAL_RE.fullmatch(rendered):
            dynamic[str(key)] = rendered[2:-1]
    return dynamic


def destination_uses_headers_helper(config: dict[str, Any], destination: str) -> bool:
    if destination == "splunk-direct":
        return True
    if destination != "external-collector":
        return False
    protocol = normalize_protocol(config["claude_code"].get("external_collector_protocol"))
    return protocol != "grpc" and bool(external_dynamic_headers(config))


def resolve_settings_scope_path(config: dict[str, Any], output_dir: Path) -> Path:
    scope = str(config["claude_code"].get("settings_scope", "user"))
    if scope == "user":
        return (Path.home() / ".claude" / "settings.json").resolve()
    if scope == "project":
        return (Path.cwd() / ".claude" / "settings.json").resolve()
    if scope == "managed":
        return (output_dir / "settings" / "managed-settings.json").resolve()
    raise UsageError(f"unknown settings_scope: {scope}")


def headers_helper_target_path(config: dict[str, Any], output_dir: Path) -> Path:
    scope = str(config["claude_code"].get("settings_scope", "user"))
    if scope == "user":
        return (Path.home() / ".claude" / "bin" / "claude-code-otel-headers.sh").resolve()
    if scope == "project":
        return (Path.cwd() / ".claude" / "bin" / "claude-code-otel-headers.sh").resolve()
    if scope == "managed":
        return (output_dir / "bin" / "claude-code-otel-headers.sh").resolve()
    raise UsageError(f"unknown settings_scope: {scope}")


def validate_spec_shape(spec_data: dict[str, Any]) -> None:
    unknown_top = sorted(set(spec_data) - set(DEFAULT_SPEC))
    if unknown_top:
        raise UsageError(f"unknown top-level spec field(s): {', '.join(unknown_top)}")
    if spec_data.get("api_version") != API_VERSION:
        raise UsageError(f"spec api_version must be {API_VERSION}")
    spec_cc = spec_data.get("claude_code")
    if not isinstance(spec_cc, dict):
        raise UsageError("spec claude_code must be an object")
    unknown_cc = sorted(set(spec_cc) - set(DEFAULT_SPEC["claude_code"]))
    if unknown_cc:
        raise UsageError(f"unknown claude_code spec field(s): {', '.join(unknown_cc)}")


def load_spec_with_args(args: argparse.Namespace) -> dict[str, Any]:
    config = copy.deepcopy(DEFAULT_SPEC)
    spec_data: dict[str, Any] = {}
    if args.spec:
        spec_data = load_structured_file(Path(args.spec).expanduser())
        validate_spec_shape(spec_data)
        config = deep_merge(config, spec_data)
    cc = config.setdefault("claude_code", {})
    spec_cc = spec_data.get("claude_code") if isinstance(spec_data, dict) else {}
    explicit_spec_galileo_endpoint = (
        isinstance(spec_cc, dict)
        and str(spec_cc.get("galileo_otel_endpoint") or "").strip() != ""
    )

    cli_updates = {
        "environment": args.environment,
        "service_name": args.service_name,
        "realm": args.realm,
        "destination": args.destination,
        "settings_scope": args.settings_scope,
        "local_collector_endpoint": args.local_collector_endpoint,
        "collector_receiver_endpoint": args.collector_receiver_endpoint,
        "external_collector_endpoint": args.external_collector_endpoint,
        "galileo_project": args.galileo_project,
        "galileo_log_stream": args.galileo_log_stream,
        "galileo_otel_endpoint": args.galileo_otel_endpoint,
        "provider_name": args.provider_name,
        "metric_export_interval_ms": args.metric_export_interval_ms,
        "logs_export_interval_ms": args.logs_export_interval_ms,
        "traces_export_interval_ms": args.traces_export_interval_ms,
        "external_collector_protocol": args.external_collector_protocol,
        "external_trace_endpoint": args.external_trace_endpoint,
        "external_metric_endpoint": args.external_metric_endpoint,
        "external_log_endpoint": args.external_log_endpoint,
    }
    for key, value in cli_updates.items():
        if value not in (None, ""):
            cc[key] = value

    if args.galileo_console_url:
        cc["galileo_console_url"] = args.galileo_console_url
    if (
        cc.get("galileo_console_url")
        and not args.galileo_otel_endpoint
        and not explicit_spec_galileo_endpoint
        and str(cc.get("galileo_otel_endpoint") or "").strip()
        in {"", DEFAULT_GALILEO_OTEL_ENDPOINT}
    ):
        cc["galileo_otel_endpoint"] = galileo_endpoint_from_console(str(cc["galileo_console_url"]))

    if args.galileo_enabled:
        cc["galileo_enabled"] = True
    if args.galileo_project and not args.disable_galileo:
        cc["galileo_enabled"] = True
    if args.enable_traces_beta:
        cc["enable_traces_beta"] = True
    if args.disable_traces_beta:
        cc["enable_traces_beta"] = False
        cc["enable_detailed_traces"] = False
    if args.enable_detailed_traces:
        cc["enable_traces_beta"] = True
        cc["enable_detailed_traces"] = True
    if args.disable_detailed_traces:
        cc["enable_detailed_traces"] = False
    if args.disable_galileo:
        cc["galileo_enabled"] = False
    if args.accept_content_capture:
        cc["accept_content_capture"] = True
    for key in (
        "log_user_prompts",
        "log_assistant_responses",
        "log_tool_details",
        "log_tool_content",
    ):
        if getattr(args, key):
            cc[key] = True
    if args.log_raw_api_bodies is not None:
        cc["log_raw_api_bodies"] = args.log_raw_api_bodies

    if args.model_alias:
        aliases = dict(cc.get("model_aliases") or {})
        for raw in args.model_alias:
            source, target = parse_model_alias(raw)
            aliases[source] = target
        cc["model_aliases"] = aliases

    if args.external_header:
        headers = dict(cc.get("external_headers") or {})
        for raw in args.external_header:
            key, value = parse_header(raw)
            headers[key] = value
        cc["external_headers"] = headers

    tls = dict(cc.get("external_tls") or {})
    for key, value in {
        "ca-certificate": args.external_ca_certificate,
        "client-certificate": args.external_client_certificate,
        "client-private-key": args.external_client_private_key,
    }.items():
        if value:
            ensure_safe_external_tls_value(f"TLS {key}", value)
            tls[key] = value
    cc["external_tls"] = tls

    if args.resource_attribute:
        attrs = dict(cc.get("resource_attributes") or {})
        for raw in args.resource_attribute:
            if "=" not in raw:
                raise UsageError("--resource-attribute must use KEY=VALUE")
            key, value = raw.split("=", 1)
            key = key.strip()
            value = value.strip()
            ensure_safe_external_value(f"resource attribute {key}", value)
            attrs[key] = value
        cc["resource_attributes"] = attrs

    cc["external_collector_protocol"] = normalize_protocol(cc.get("external_collector_protocol"))
    cc["log_raw_api_bodies"] = normalize_raw_api_bodies(cc.get("log_raw_api_bodies"))
    return config


def validate_config(config: dict[str, Any]) -> tuple[list[str], list[str]]:
    cc = config["claude_code"]
    errors: list[str] = []
    warnings: list[str] = []

    for field in ("service_name", "environment"):
        value = str(cc.get(field) or "").strip()
        if not value:
            errors.append(f"{field} is required")
        elif any(ord(char) < 32 or ord(char) == 127 for char in value):
            errors.append(f"{field} must not contain control characters")

    for field in ("external_headers", "external_tls", "resource_attributes", "model_aliases"):
        if not isinstance(cc.get(field), dict):
            errors.append(f"{field} must be an object")

    boolean_fields = (
        "enable_traces_beta",
        "enable_detailed_traces",
        "galileo_enabled",
        "metrics_include_session_id",
        "metrics_include_version",
        "metrics_include_account_uuid",
        "metrics_include_entrypoint",
        "metrics_include_resource_attributes",
        "log_user_prompts",
        "log_assistant_responses",
        "log_tool_details",
        "log_tool_content",
        "accept_content_capture",
    )
    for field in boolean_fields:
        value = cc.get(field)
        if not isinstance(value, bool) and str(value).strip().lower() not in {
            "0",
            "1",
            "false",
            "no",
            "off",
            "on",
            "true",
            "yes",
        }:
            errors.append(f"{field} must be a boolean")

    for field in ("metric_export_interval_ms", "logs_export_interval_ms", "traces_export_interval_ms"):
        try:
            if int(cc.get(field)) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"{field} must be a positive integer")

    temporality = str(cc.get("metrics_temporality_preference") or "").strip().lower()
    if temporality not in VALID_TEMPORALITY_PREFERENCES:
        errors.append(
            "metrics_temporality_preference must be one of "
            + ", ".join(sorted(VALID_TEMPORALITY_PREFERENCES))
        )
    else:
        cc["metrics_temporality_preference"] = temporality

    destination = str(cc.get("destination", "local-collector"))
    if destination not in VALID_DESTINATIONS:
        errors.append(f"destination must be one of {', '.join(sorted(VALID_DESTINATIONS))}")
        return errors, warnings

    scope = str(cc.get("settings_scope", "user"))
    if scope not in VALID_SCOPES:
        errors.append(f"settings_scope must be one of {', '.join(sorted(VALID_SCOPES))}")

    protocol = normalize_protocol(cc.get("external_collector_protocol", "http/protobuf"))
    cc["external_collector_protocol"] = protocol
    if protocol not in VALID_PROTOCOLS:
        errors.append(
            "external_collector_protocol must be one of "
            f"{', '.join(sorted(VALID_PROTOCOL_INPUTS))}"
        )

    for target in destinations_for(destination):
        if target == "local-collector":
            try:
                normalize_local_collector_endpoint(cc.get("local_collector_endpoint"))
            except UsageError as exc:
                errors.append(str(exc))
            try:
                normalize_collector_receiver_endpoint(
                    cc.get("collector_receiver_endpoint"),
                    cc.get("local_collector_endpoint"),
                )
            except UsageError as exc:
                errors.append(str(exc))
        if target == "external-collector":
            shared_endpoint = str(cc.get("external_collector_endpoint") or "")
            traces_enabled = bool_config(cc.get("enable_traces_beta"))
            if shared_endpoint:
                try:
                    ensure_safe_external_value("external_collector_endpoint", shared_endpoint)
                except UsageError as exc:
                    errors.append(str(exc))
            if not shared_endpoint:
                if traces_enabled and not cc.get("external_trace_endpoint"):
                    errors.append("external collector mode requires --external-trace-endpoint when traces are enabled")
                if not cc.get("external_metric_endpoint"):
                    errors.append("external collector mode requires --external-metric-endpoint or --external-collector-endpoint")
                if not cc.get("external_log_endpoint"):
                    errors.append("external collector mode requires --external-log-endpoint or --external-collector-endpoint")
            for label, value in (
                ("external_collector_endpoint", cc.get("external_collector_endpoint")),
                ("external_trace_endpoint", cc.get("external_trace_endpoint")),
                ("external_metric_endpoint", cc.get("external_metric_endpoint")),
                ("external_log_endpoint", cc.get("external_log_endpoint")),
            ):
                if value:
                    try:
                        ensure_safe_external_value(label, str(value))
                    except UsageError as exc:
                        errors.append(str(exc))
        if target == "splunk-direct":
            if not cc.get("realm"):
                errors.append("splunk-direct requires --realm")

    # Realm feeds directly into rendered ingest URLs (splunk-direct endpoints and the
    # collector overlay's signalfx/traces exporters), so validate its shape whenever it
    # will be used. local-collector/all render the overlay; splunk-direct/all render
    # per-signal endpoints. external-collector does not use the realm.
    if destination in {"local-collector", "splunk-direct", "all"} and cc.get("realm"):
        try:
            validate_realm(cc.get("realm"))
        except UsageError as exc:
            errors.append(str(exc))

    galileo_enabled = bool_config(cc.get("galileo_enabled"))
    if str(cc.get("galileo_console_url") or "").strip():
        try:
            galileo_endpoint_from_console(str(cc.get("galileo_console_url")))
        except UsageError as exc:
            errors.append(str(exc))
    if galileo_enabled and destination in {"local-collector", "external-collector", "all"}:
        if not bool_config(cc.get("enable_traces_beta")):
            errors.append("Galileo integration requires Claude Code traces beta because Galileo ingests traces only")
        if not str(cc.get("galileo_project") or "").strip():
            errors.append("Galileo integration requires --galileo-project when enabled")
        if not str(cc.get("galileo_console_url") or "").strip() and not str(
            cc.get("galileo_otel_endpoint") or ""
        ).strip():
            errors.append(
                "Galileo integration requires the user's instance URL via "
                "--galileo-console-url or an explicit --galileo-otel-endpoint; do not assume the public tenant"
            )
        else:
            try:
                parse_galileo_endpoint(cc.get("galileo_otel_endpoint"))
            except UsageError as exc:
                errors.append(str(exc))

    # SEC-03: galileo_project and galileo_log_stream are baked verbatim into the
    # collector overlay headers and the handoff doc. Reject token-like values so a
    # pasted secret cannot be persisted to a rendered file.
    for label, value in (
        ("galileo_project", cc.get("galileo_project")),
        ("galileo_log_stream", cc.get("galileo_log_stream")),
    ):
        if value:
            try:
                ensure_safe_galileo_route_value(label, str(value))
            except UsageError as exc:
                errors.append(str(exc))
    if galileo_enabled and destination == "splunk-direct":
        warnings.append(
            "Galileo is enabled but destination is splunk-direct; "
            "Galileo fan-out requires local-collector or external-collector and is skipped"
        )

    content_flags = [
        ("log_user_prompts", cc.get("log_user_prompts")),
        ("log_assistant_responses", cc.get("log_assistant_responses")),
        ("log_tool_details", cc.get("log_tool_details")),
        ("log_tool_content", cc.get("log_tool_content")),
        ("log_raw_api_bodies", bool(cc.get("log_raw_api_bodies"))),
    ]
    if any(bool_config(value) for _, value in content_flags) and not bool_config(cc.get("accept_content_capture")):
        errors.append(
            "prompt/response/tool content capture requires --accept-content-capture"
        )

    if bool_config(cc.get("enable_detailed_traces")):
        if not bool_config(cc.get("enable_traces_beta")):
            errors.append("detailed beta tracing requires base traces beta")
        if not bool_config(cc.get("accept_content_capture")):
            errors.append(
                "detailed beta tracing can emit experimental content-bearing span attributes and requires --accept-content-capture"
            )

    if bool_config(cc.get("log_tool_content")) and not bool_config(cc.get("enable_traces_beta")):
        warnings.append("OTEL_LOG_TOOL_CONTENT is set but traces beta is disabled; tool content is only attached to spans")

    if isinstance(cc.get("external_headers"), dict):
        for key, value in (cc.get("external_headers") or {}).items():
            try:
                ensure_safe_external_header(str(key), str(value))
            except UsageError as exc:
                errors.append(str(exc))
            if protocol == "grpc" and ENV_PLACEHOLDER_LOCAL_RE.fullmatch(str(value)):
                errors.append(
                    f"external header {key} uses an environment placeholder, but Claude Code's "
                    "otelHeadersHelper does not apply to gRPC; use OTLP/HTTP or inject the resolved header at process start"
                )
    if isinstance(cc.get("external_tls"), dict):
        unknown_tls = sorted(
            set(cc.get("external_tls") or {})
            - {"ca-certificate", "client-certificate", "client-private-key"}
        )
        if unknown_tls:
            errors.append(f"unknown external_tls field(s): {', '.join(unknown_tls)}")
        for key, value in (cc.get("external_tls") or {}).items():
            try:
                ensure_safe_external_tls_value(f"TLS {key}", str(value))
            except UsageError as exc:
                errors.append(str(exc))
            if ENV_PLACEHOLDER_LOCAL_RE.fullmatch(str(value)):
                errors.append(
                    f"external TLS {key} uses an environment placeholder, but settings.json env values "
                    "are not shell-expanded; use a literal certificate path"
                )
    if isinstance(cc.get("resource_attributes"), dict):
        for key, value in (cc.get("resource_attributes") or {}).items():
            if not RESOURCE_ATTRIBUTE_KEY_RE.fullmatch(str(key)):
                errors.append(
                    f"resource attribute key {key!r} must start with a letter or underscore and contain only letters, digits, dot, underscore, or hyphen"
                )
            try:
                ensure_safe_external_value(f"resource attribute {key}", str(value))
            except UsageError as exc:
                errors.append(str(exc))

    provider_name = str(cc.get("provider_name") or "").strip()
    if provider_name:
        try:
            ensure_safe_external_value("provider_name", provider_name)
        except UsageError as exc:
            errors.append(str(exc))
    if isinstance(cc.get("model_aliases"), dict):
        for source, target in (cc.get("model_aliases") or {}).items():
            try:
                parse_model_alias(f"{source}={target}")
            except UsageError as exc:
                errors.append(str(exc))

    try:
        cc["log_raw_api_bodies"] = normalize_raw_api_bodies(cc.get("log_raw_api_bodies"))
    except UsageError as exc:
        errors.append(str(exc))

    return errors, warnings


def _bool_env(value: bool) -> str:
    return "true" if value else "false"


def render_env_dict(config: dict[str, Any], output_dir: Path) -> dict[str, str]:
    cc = config["claude_code"]
    destination = str(cc["destination"])
    if destination == "all":
        raise UsageError("render_env_dict cannot be called for destination=all; call once per rendered destination")

    env: dict[str, str] = {"CLAUDE_CODE_ENABLE_TELEMETRY": "1"}

    env["OTEL_METRICS_EXPORTER"] = "otlp"
    env["OTEL_LOGS_EXPORTER"] = "otlp"

    traces_enabled = bool_config(cc.get("enable_traces_beta"))
    # Detailed tracing only makes sense when the base traces beta is on.
    detailed_traces = traces_enabled and bool_config(cc.get("enable_detailed_traces"))
    if traces_enabled:
        env["OTEL_TRACES_EXPORTER"] = "otlp"
        env["CLAUDE_CODE_ENHANCED_TELEMETRY_BETA"] = "1"

    # BETA_TRACING_ENDPOINT is a SEPARATE endpoint (distinct from
    # OTEL_EXPORTER_OTLP_TRACES_ENDPOINT) that detailed beta tracing requires. It must
    # point at wherever traces are sent so detailed spans reach the same backend.
    beta_tracing_endpoint = ""

    if destination == "local-collector":
        endpoint = normalize_local_collector_endpoint(cc["local_collector_endpoint"])
        env["OTEL_EXPORTER_OTLP_PROTOCOL"] = "http/protobuf"
        env["OTEL_EXPORTER_OTLP_ENDPOINT"] = endpoint
        beta_tracing_endpoint = endpoint
    elif destination == "splunk-direct":
        realm = str(cc["realm"])
        base = f"https://ingest.{realm}.observability.splunkcloud.com"
        env["OTEL_EXPORTER_OTLP_PROTOCOL"] = "http/protobuf"
        env["OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"] = f"{base}/v2/datapoint/otlp"
        env["OTEL_EXPORTER_OTLP_LOGS_ENDPOINT"] = f"{base}/v2/log/otlp"
        if traces_enabled:
            traces_ep = f"{base}/v2/trace/otlp"
            env["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"] = traces_ep
            beta_tracing_endpoint = traces_ep
    elif destination == "external-collector":
        protocol = normalize_protocol(cc.get("external_collector_protocol", "http/protobuf"))
        env["OTEL_EXPORTER_OTLP_PROTOCOL"] = protocol
        shared_ep = str(cc.get("external_collector_endpoint") or "")
        trace_ep = str(cc.get("external_trace_endpoint") or "")
        metric_ep = str(cc.get("external_metric_endpoint") or "")
        log_ep = str(cc.get("external_log_endpoint") or "")
        if shared_ep:
            env["OTEL_EXPORTER_OTLP_ENDPOINT"] = shared_ep
        if trace_ep and traces_enabled:
            env["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"] = trace_ep
        if metric_ep:
            env["OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"] = metric_ep
        if log_ep:
            env["OTEL_EXPORTER_OTLP_LOGS_ENDPOINT"] = log_ep
        external_headers = cc.get("external_headers") or {}
        if external_headers:
            # Claude does not shell-expand ${NAME} inside settings.json env values.
            # Keep all-literal sets static. If any value is dynamic, let
            # otelHeadersHelper return the complete set so behavior does not depend
            # on undocumented static/dynamic header merge semantics.
            static_headers = (
                {str(key): str(value) for key, value in external_headers.items()}
                if not external_dynamic_headers(config)
                else {}
            )
            if static_headers:
                header_pairs = [f"{k}={v}" for k, v in sorted(static_headers.items())]
                env["OTEL_EXPORTER_OTLP_HEADERS"] = ",".join(header_pairs)
        external_tls = cc.get("external_tls") or {}
        # Claude Code's Node HTTP exporter uses Claude/Node-specific mTLS vars;
        # only the gRPC exporter consumes the standard OTel certificate vars.
        tls_env = (
            {
                "ca-certificate": "OTEL_EXPORTER_OTLP_CERTIFICATE",
                "client-certificate": "OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE",
                "client-private-key": "OTEL_EXPORTER_OTLP_CLIENT_KEY",
            }
            if protocol == "grpc"
            else {
                "ca-certificate": "NODE_EXTRA_CA_CERTS",
                "client-certificate": "CLAUDE_CODE_CLIENT_CERT",
                "client-private-key": "CLAUDE_CODE_CLIENT_KEY",
            }
        )
        for tls_key, env_key in tls_env.items():
            value = str(external_tls.get(tls_key) or "")
            if value:
                env[env_key] = value
        # Detailed traces follow the trace endpoint (explicit trace endpoint wins,
        # else the shared endpoint).
        beta_tracing_endpoint = (trace_ep if trace_ep and traces_enabled else shared_ep)

    if detailed_traces and beta_tracing_endpoint:
        env["ENABLE_BETA_TRACING_DETAILED"] = "1"
        env["BETA_TRACING_ENDPOINT"] = beta_tracing_endpoint

    metric_interval = int(cc.get("metric_export_interval_ms", 60000))
    if metric_interval != 60000:
        env["OTEL_METRIC_EXPORT_INTERVAL"] = str(metric_interval)
    logs_interval = int(cc.get("logs_export_interval_ms", 5000))
    if logs_interval != 5000:
        env["OTEL_LOGS_EXPORT_INTERVAL"] = str(logs_interval)
    traces_interval = int(cc.get("traces_export_interval_ms", 5000))
    if traces_enabled and traces_interval != 5000:
        env["OTEL_TRACES_EXPORT_INTERVAL"] = str(traces_interval)

    temporality = str(cc.get("metrics_temporality_preference", "delta"))
    if temporality != "delta":
        env["OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE"] = temporality

    if not bool_config(cc.get("metrics_include_session_id", True)):
        env["OTEL_METRICS_INCLUDE_SESSION_ID"] = "false"
    if bool_config(cc.get("metrics_include_version")):
        env["OTEL_METRICS_INCLUDE_VERSION"] = "true"
    if not bool_config(cc.get("metrics_include_account_uuid", True)):
        env["OTEL_METRICS_INCLUDE_ACCOUNT_UUID"] = "false"
    if bool_config(cc.get("metrics_include_entrypoint")):
        env["OTEL_METRICS_INCLUDE_ENTRYPOINT"] = "true"
    # CC-OTEL-04: governs whether OTEL_RESOURCE_ATTRIBUTES keys (e.g. the skill's
    # custom department/team.id) are stamped on every datapoint. Default true;
    # set false to keep them in the OTLP resource block only and cut cardinality.
    if not bool_config(cc.get("metrics_include_resource_attributes", True)):
        env["OTEL_METRICS_INCLUDE_RESOURCE_ATTRIBUTES"] = "false"

    if bool_config(cc.get("log_user_prompts")):
        env["OTEL_LOG_USER_PROMPTS"] = "1"
    if bool_config(cc.get("log_assistant_responses")):
        env["OTEL_LOG_ASSISTANT_RESPONSES"] = "1"
    elif bool_config(cc.get("log_user_prompts")):
        # Claude v2.1.193+ falls back to OTEL_LOG_USER_PROMPTS when the response
        # flag is absent. Emit an explicit zero so prompt-only consent stays
        # prompt-only.
        env["OTEL_LOG_ASSISTANT_RESPONSES"] = "0"
    if bool_config(cc.get("log_tool_details")):
        env["OTEL_LOG_TOOL_DETAILS"] = "1"
    if bool_config(cc.get("log_tool_content")):
        env["OTEL_LOG_TOOL_CONTENT"] = "1"
    raw_api_bodies = normalize_raw_api_bodies(cc.get("log_raw_api_bodies"))
    if raw_api_bodies:
        env["OTEL_LOG_RAW_API_BODIES"] = raw_api_bodies

    resource_attrs: dict[str, str] = {}
    resource_attrs["service.name"] = str(cc["service_name"])
    resource_attrs["sf_service"] = str(cc["service_name"])
    resource_attrs["deployment.environment"] = str(cc["environment"])
    resource_attrs["deployment.environment.name"] = str(cc["environment"])
    # Splunk Observability UI environment pickers, including AI overview, use
    # sf_environment. Keep the OTel deployment.environment keys for semantic
    # correctness, but stamp sf_environment explicitly so Claude appears under
    # the expected Environment filter.
    resource_attrs["sf_environment"] = str(cc["environment"])
    for key, value in (cc.get("resource_attributes") or {}).items():
        resource_attrs[str(key)] = str(value)
    env["OTEL_RESOURCE_ATTRIBUTES"] = ",".join(
        f"{k}={encode_resource_attribute_value(v)}" for k, v in sorted(resource_attrs.items())
    )
    env["OTEL_SERVICE_NAME"] = str(cc["service_name"])

    return env


def render_settings_file(config: dict[str, Any], destination: str, output_dir: Path) -> str:
    env_config = deep_merge({}, config)
    env_config["claude_code"] = dict(env_config["claude_code"])
    env_config["claude_code"]["destination"] = destination
    env = render_env_dict(env_config, output_dir)
    settings: dict[str, Any] = {"env": env}
    if destination_uses_headers_helper(config, destination):
        helper_path = headers_helper_target_path(config, output_dir)
        settings["otelHeadersHelper"] = str(helper_path)
    settings["_managedBy"] = MANAGED_SETTINGS_MARKER
    return json.dumps(settings, indent=2, sort_keys=True) + "\n"


def render_env_file(config: dict[str, Any], destination: str, output_dir: Path) -> str:
    env_config = deep_merge({}, config)
    env_config["claude_code"] = dict(env_config["claude_code"])
    env_config["claude_code"]["destination"] = destination
    env = render_env_dict(env_config, output_dir)
    lines = [
        "#!/usr/bin/env bash",
        "# Claude Code OTel environment helper.",
        f"# Destination: {destination}",
        "# Source this file before starting Claude Code to enable native OTel telemetry.",
        "# Token values are never written here; supply them via SPLUNK_O11Y_TOKEN_FILE",
        "# or GALILEO_API_KEY_FILE and the otelHeadersHelper script.",
        "",
    ]
    if destination == "splunk-direct":
        lines.extend(
            [
                "# Direct Splunk ingest expects X-SF-TOKEN via the otelHeadersHelper.",
                "# Ensure SPLUNK_O11Y_TOKEN_FILE points to a chmod 600 file containing the token.",
                "",
            ]
        )
    elif destination_uses_headers_helper(config, destination):
        lines.extend(
            [
                "# Placeholder-backed external headers are resolved by otelHeadersHelper.",
                "# Export the referenced variables before starting Claude Code.",
                "",
            ]
        )
    for key in sorted(env):
        lines.append(f"export {key}={shell_quote(env[key])}")
    lines.append("")
    return "\n".join(lines)


def render_model_alias_statements(config: dict[str, Any], context: str) -> str:
    aliases = config["claude_code"].get("model_aliases") or {}
    if not isinstance(aliases, dict):
        return ""
    if context == "span":
        attribute = 'span.attributes["gen_ai.request.model"]'
        guard = '(span.attributes["span.type"] == "llm_request" or span.name == "claude_code.llm_request") and '
    elif context == "datapoint":
        attribute = 'datapoint.attributes["gen_ai.request.model"]'
        guard = ""
    else:  # pragma: no cover - internal call contract
        raise ValueError(f"unsupported model alias context: {context}")
    return "\n".join(
        f"          - set({attribute}, {yaml_quote(str(target))}) where {guard}{attribute} == {yaml_quote(str(source))}"
        for source, target in sorted(aliases.items())
    )


def render_galileo_tool_schema_statements() -> str:
    """Flatten Claude's advertised-tool inventory into OpenInference schemas.

    Detailed Claude spans expose ``tools`` as a JSON array of ``name``/``hash``
    objects. Galileo's Tool Selection Quality scorer instead looks for the
    flattened OpenInference ``llm.tools.N.tool.json_schema`` attributes. Build a
    temporary map, flatten it, rewrite its keys and values, then merge it into
    the span. The operation is dynamic, so MCP and future tool inventories are
    not silently capped. Only the observed name is retained; Claude emits full
    descriptions and parameter schemas as separate log records, so inventing
    them on the span would make evaluation misleading.
    """

    return "\n".join(
        [
            '          - set(span.attributes["claude_code.galileo.available_tools_count"], Len(ParseJSON(span.attributes["tools"]))) where span.attributes["span.type"] == "llm_request" and span.attributes["tools"] != nil and IsList(ParseJSON(span.attributes["tools"]))',
            '          - set(span.attributes["gen_ai.tool.definitions"], span.attributes["tools"]) where span.attributes["span.type"] == "llm_request" and span.attributes["tools"] != nil',
            '          - replace_pattern(span.attributes["gen_ai.tool.definitions"], "\\\\{\\\"name\\\":\\\"([^\\\"]+)\\\",\\\"hash\\\":\\\"[^\\\"]+\\\"\\\\}", "{\\\"type\\\":\\\"function\\\",\\\"name\\\":\\\"$$1\\\"}") where span.attributes["span.type"] == "llm_request" and span.attributes["gen_ai.tool.definitions"] != nil',
            '          - set(span.cache["claude_tools"], ParseJSON(Concat(["{\\\"llm\\\":{\\\"tools\\\":", span.attributes["tools"], "}}"], ""))) where span.attributes["span.type"] == "llm_request" and span.attributes["tools"] != nil',
            '          - flatten(span.cache["claude_tools"]) where span.attributes["span.type"] == "llm_request" and IsMap(span.cache["claude_tools"])',
            '          - delete_matching_keys(span.cache["claude_tools"], "^llm\\\\.tools\\\\.[0-9]+\\\\.hash$") where span.attributes["span.type"] == "llm_request" and IsMap(span.cache["claude_tools"])',
            '          - replace_all_patterns(span.cache["claude_tools"], "key", "^llm\\\\.tools\\\\.([0-9]+)\\\\.name$", "llm.tools.$$1.tool.json_schema") where span.attributes["span.type"] == "llm_request" and IsMap(span.cache["claude_tools"])',
            '          - replace_all_patterns(span.cache["claude_tools"], "value", "^(.*)$", "{\\\"type\\\":\\\"function\\\",\\\"function\\\":{\\\"name\\\":\\\"$$1\\\"}}") where span.attributes["span.type"] == "llm_request" and IsMap(span.cache["claude_tools"])',
            '          - merge_maps(span.attributes, span.cache["claude_tools"], "upsert") where span.attributes["span.type"] == "llm_request" and IsMap(span.cache["claude_tools"])',
            '          - delete_key(span.attributes, "llm.tools") where span.attributes["span.type"] == "llm_request"',
            '          - delete_key(span.attributes, "tools") where span.attributes["span.type"] == "llm_request"',
            '          - delete_key(span.cache, "claude_tools") where span.attributes["span.type"] == "llm_request"',
        ]
    )


def render_collector_overlay(config: dict[str, Any]) -> str:
    cc = config["claude_code"]
    realm = str(cc.get("realm") or "us0")
    service_name = str(cc["service_name"])
    environment = str(cc["environment"])
    receiver_endpoint = normalize_collector_receiver_endpoint(
        cc.get("collector_receiver_endpoint"), cc["local_collector_endpoint"]
    )
    galileo_enabled = bool_config(cc.get("galileo_enabled"))
    galileo_project = str(cc.get("galileo_project") or "")
    galileo_log_stream = str(cc.get("galileo_log_stream") or "default")
    galileo_endpoint_str = str(cc.get("galileo_otel_endpoint") or "")
    if galileo_enabled:
        parse_galileo_endpoint(galileo_endpoint_str)
    trace_exporters = [
        "otlp_http/claude_code_traces",
        "span_metrics/claude_code_genai",
    ]
    provider_name = str(cc.get("provider_name") or "").strip()
    if provider_name:
        span_provider_statements = (
            f'          - set(span.attributes["gen_ai.provider.name"], {yaml_quote(provider_name)}) '
            'where span.attributes["span.type"] == "llm_request" or span.name == "claude_code.llm_request"'
        )
        datapoint_provider_statements = (
            f'          - set(datapoint.attributes["gen_ai.provider.name"], {yaml_quote(provider_name)})'
        )
    else:
        bedrock_model_pattern = "^(arn:aws:bedrock:|(?:[a-z0-9-]+\\.)?anthropic\\.claude)"
        span_provider_statements = "\n".join(
            [
                f'          - set(span.attributes["gen_ai.provider.name"], "aws.bedrock") where (span.attributes["span.type"] == "llm_request" or span.name == "claude_code.llm_request") and span.attributes["gen_ai.provider.name"] == nil and span.attributes["gen_ai.request.model"] != nil and IsMatch(span.attributes["gen_ai.request.model"], {yaml_quote(bedrock_model_pattern)})',
                '          - set(span.attributes["gen_ai.provider.name"], "anthropic") where (span.attributes["span.type"] == "llm_request" or span.name == "claude_code.llm_request") and span.attributes["gen_ai.provider.name"] == nil',
            ]
        )
        datapoint_provider_statements = "\n".join(
            [
                f'          - set(datapoint.attributes["gen_ai.provider.name"], "aws.bedrock") where datapoint.attributes["gen_ai.provider.name"] == nil and datapoint.attributes["gen_ai.request.model"] != nil and IsMatch(datapoint.attributes["gen_ai.request.model"], {yaml_quote(bedrock_model_pattern)})',
                '          - set(datapoint.attributes["gen_ai.provider.name"], "anthropic") where datapoint.attributes["gen_ai.provider.name"] == nil',
            ]
        )
    span_model_alias_statements = render_model_alias_statements(config, "span")
    datapoint_model_alias_statements = render_model_alias_statements(config, "datapoint")
    galileo_tool_schema_statements = render_galileo_tool_schema_statements()

    galileo_block = ""
    if galileo_enabled:
        galileo_block = f"""  otlp_http/galileo:
    endpoint: {yaml_quote(galileo_endpoint_str)}
    headers:
      Galileo-API-Key: "${{env:GALILEO_API_KEY}}"
      project: {yaml_quote(galileo_project)}
      logstream: {yaml_quote(galileo_log_stream)}
"""

    return f"""# Local collector overlay for Claude Code OTel.
# Requires a collector distribution containing the signal_to_metrics connector.
# otel/opentelemetry-collector-contrib:0.154.0 is validated. The stock Splunk
# Distribution v0.154.2 omits this connector and cannot produce the GenAI token
# histogram required by Splunk AI Agent Monitoring.
receivers:
  otlp/claude_code:
    protocols:
      http:
        endpoint: {yaml_quote(receiver_endpoint)}

processors:
  batch/claude_code: {{}}
  resource/claude_code:
    attributes:
      - key: service.name
        value: {yaml_quote(service_name)}
        action: upsert
      - key: deployment.environment.name
        value: {yaml_quote(environment)}
        action: upsert
      - key: deployment.environment
        value: {yaml_quote(environment)}
        action: upsert
      - key: sf_environment
        value: {yaml_quote(environment)}
        action: upsert
      - key: sf_service
        value: {yaml_quote(service_name)}
        action: upsert
      - key: gen_ai.agent.name
        value: {yaml_quote(service_name)}
        action: insert
      - key: gen_ai.framework
        value: claude-code
        action: insert
  # Map Claude Code's native beta span attributes onto the OpenTelemetry GenAI
  # semantic conventions that Splunk AI Agent Monitoring (the "AI overview"
  # dashboard) and Galileo read. Claude Code llm_request spans carry
  # gen_ai.system + gen_ai.request.model but omit gen_ai.operation.name, emit
  # token counts as input_tokens/output_tokens (not gen_ai.usage.*), and use
  # span kind Internal instead of Client. Splunk identifies AI agents from span
  # attributes, so stamp gen_ai.agent.name onto Claude spans and mark the root
  # interaction span as an invoke_workflow operation. Scope chat mapping by the
  # native span.type so only real LLM calls become chat spans (tool spans stay out
  # of the chat-span count).
  transform/claude_code_genai:
    error_mode: ignore
    trace_statements:
      - context: span
        statements:
          - set(span.attributes["gen_ai.agent.name"], {yaml_quote(service_name)}) where span.attributes["gen_ai.agent.name"] == nil
          - set(span.attributes["gen_ai.workflow.name"], {yaml_quote(service_name)}) where (span.attributes["span.type"] == "interaction" or span.name == "claude_code.interaction") and span.attributes["gen_ai.workflow.name"] == nil
          - set(span.attributes["gen_ai.operation.name"], "invoke_workflow") where (span.attributes["span.type"] == "interaction" or span.name == "claude_code.interaction") and span.attributes["gen_ai.operation.name"] == nil
          - set(span.attributes["gen_ai.operation.name"], "chat") where span.attributes["span.type"] == "llm_request" or span.name == "claude_code.llm_request"
          - set(span.attributes["gen_ai.system"], "anthropic") where (span.attributes["span.type"] == "llm_request" or span.name == "claude_code.llm_request") and span.attributes["gen_ai.system"] == nil
          - set(span.attributes["gen_ai.request.model"], span.attributes["model"]) where (span.attributes["span.type"] == "llm_request" or span.name == "claude_code.llm_request") and span.attributes["gen_ai.request.model"] == nil and span.attributes["model"] != nil
{span_provider_statements}
          - set(span.attributes["aws.bedrock.inference_profile_arn"], span.attributes["gen_ai.request.model"]) where (span.attributes["span.type"] == "llm_request" or span.name == "claude_code.llm_request") and span.attributes["gen_ai.request.model"] != nil and IsMatch(span.attributes["gen_ai.request.model"], "^arn:aws:bedrock:")
{span_model_alias_statements}
          - set(span.attributes["gen_ai.response.model"], span.attributes["gen_ai.request.model"]) where (span.attributes["span.type"] == "llm_request" or span.name == "claude_code.llm_request") and span.attributes["gen_ai.response.model"] == nil and span.attributes["gen_ai.request.model"] != nil
          - set(span.kind, SPAN_KIND_CLIENT) where span.attributes["span.type"] == "llm_request" or span.name == "claude_code.llm_request"
          - set(span.attributes["gen_ai.usage.input_tokens"], span.attributes["input_tokens"]) where span.attributes["input_tokens"] != nil
          - set(span.attributes["gen_ai.usage.input_tokens"], 0) where span.attributes["gen_ai.usage.input_tokens"] == nil and (span.attributes["cache_read_tokens"] != nil or span.attributes["cache_creation_tokens"] != nil)
          - set(span.attributes["gen_ai.usage.cache_read.input_tokens"], span.attributes["cache_read_tokens"]) where span.attributes["cache_read_tokens"] != nil
          - set(span.attributes["gen_ai.usage.cache_creation.input_tokens"], span.attributes["cache_creation_tokens"]) where span.attributes["cache_creation_tokens"] != nil
          - set(span.attributes["gen_ai.usage.input_tokens"], span.attributes["gen_ai.usage.input_tokens"] + span.attributes["cache_read_tokens"]) where span.attributes["cache_read_tokens"] != nil
          - set(span.attributes["gen_ai.usage.input_tokens"], span.attributes["gen_ai.usage.input_tokens"] + span.attributes["cache_creation_tokens"]) where span.attributes["cache_creation_tokens"] != nil
          - set(span.attributes["gen_ai.usage.output_tokens"], span.attributes["output_tokens"]) where span.attributes["output_tokens"] != nil
          - set(span.name, Concat(["chat ", span.attributes["gen_ai.request.model"]], "")) where (span.attributes["span.type"] == "llm_request" or span.name == "claude_code.llm_request") and span.attributes["gen_ai.request.model"] != nil
  # Galileo reads content and agent/tool structure from OTel GenAI or
  # OpenInference attributes, while Claude Code emits detailed content under
  # native keys. Keep this transform on the Galileo-only branch so prompt,
  # response, tool input, and tool output are not copied into the Splunk branch.
  #
  # Context groups execute in configuration order. The first span group records
  # the final model output on its resource, the next span group copies it to the
  # interaction root, and the resource group removes the temporary value before
  # export. Claude ends the final llm_request immediately before the interaction,
  # so both are present in the final OTLP batch.
  transform/claude_code_galileo:
    error_mode: ignore
    trace_statements:
      - context: spanevent
        statements:
          - set(span.attributes["gen_ai.tool.call.result"], spanevent.attributes["output"]) where (span.attributes["span.type"] == "tool" or span.name == "claude_code.tool") and spanevent.name == "tool.output" and spanevent.attributes["output"] != nil
          - set(span.attributes["output.value"], spanevent.attributes["output"]) where (span.attributes["span.type"] == "tool" or span.name == "claude_code.tool") and spanevent.name == "tool.output" and spanevent.attributes["output"] != nil
          - set(span.attributes["output.mime_type"], "text/plain") where (span.attributes["span.type"] == "tool" or span.name == "claude_code.tool") and spanevent.name == "tool.output" and spanevent.attributes["output"] != nil
      - context: span
        statements:
          - set(resource.attributes["{GALILEO_OUTPUT_SCRATCH_ATTRIBUTE}"], span.attributes["response.model_output"]) where span.attributes["span.type"] == "llm_request" and span.attributes["response.model_output"] != nil
          - set(span.attributes["input.value"], span.attributes["user_prompt"]) where (span.attributes["span.type"] == "interaction" or span.name == "claude_code.interaction") and span.attributes["user_prompt"] != nil
          - set(span.attributes["input.mime_type"], "text/plain") where (span.attributes["span.type"] == "interaction" or span.name == "claude_code.interaction") and span.attributes["user_prompt"] != nil
          - set(span.attributes["gen_ai.request.prompt"], span.attributes["user_prompt"]) where (span.attributes["span.type"] == "interaction" or span.name == "claude_code.interaction") and span.attributes["user_prompt"] != nil
          - set(span.attributes["openinference.span.kind"], "AGENT") where span.attributes["span.type"] == "interaction" or span.name == "claude_code.interaction"
          - set(span.attributes["gen_ai.provider.name"], "anthropic") where (span.attributes["span.type"] == "interaction" or span.name == "claude_code.interaction") and span.attributes["gen_ai.provider.name"] == nil
          - set(span.attributes["input.value"], span.attributes["new_context"]) where span.attributes["span.type"] == "llm_request" and span.attributes["new_context"] != nil
          - set(span.attributes["input.mime_type"], "text/plain") where span.attributes["span.type"] == "llm_request" and span.attributes["new_context"] != nil
          - set(span.attributes["output.value"], span.attributes["response.model_output"]) where span.attributes["span.type"] == "llm_request" and span.attributes["response.model_output"] != nil
          - set(span.attributes["output.mime_type"], "text/plain") where span.attributes["span.type"] == "llm_request" and span.attributes["response.model_output"] != nil
          - set(span.attributes["gen_ai.request.prompt"], span.attributes["new_context"]) where span.attributes["span.type"] == "llm_request" and span.attributes["new_context"] != nil
          - set(span.attributes["gen_ai.response.content"], span.attributes["response.model_output"]) where span.attributes["span.type"] == "llm_request" and span.attributes["response.model_output"] != nil
          - set(span.attributes["llm.input_messages.0.message.role"], "user") where span.attributes["span.type"] == "llm_request" and span.attributes["new_context"] != nil
          - set(span.attributes["llm.input_messages.0.message.content"], span.attributes["new_context"]) where span.attributes["span.type"] == "llm_request" and span.attributes["new_context"] != nil
          - set(span.attributes["llm.output_messages.0.message.role"], "assistant") where span.attributes["span.type"] == "llm_request" and span.attributes["response.model_output"] != nil
          - set(span.attributes["llm.output_messages.0.message.content"], span.attributes["response.model_output"]) where span.attributes["span.type"] == "llm_request" and span.attributes["response.model_output"] != nil
{galileo_tool_schema_statements}
          - set(span.attributes["openinference.span.kind"], "LLM") where span.attributes["span.type"] == "llm_request"
          - set(span.attributes["gen_ai.operation.name"], "execute_tool") where span.attributes["span.type"] == "tool" or span.name == "claude_code.tool"
          - set(span.attributes["gen_ai.system"], "anthropic") where (span.attributes["span.type"] == "tool" or span.name == "claude_code.tool") and span.attributes["gen_ai.system"] == nil
          - set(span.attributes["gen_ai.tool.name"], span.attributes["tool_name"]) where (span.attributes["span.type"] == "tool" or span.name == "claude_code.tool") and span.attributes["tool_name"] != nil
          - set(span.attributes["gen_ai.tool.call.arguments"], span.attributes["tool_input"]) where (span.attributes["span.type"] == "tool" or span.name == "claude_code.tool") and span.attributes["tool_input"] != nil
          - set(span.attributes["input.value"], span.attributes["tool_input"]) where (span.attributes["span.type"] == "tool" or span.name == "claude_code.tool") and span.attributes["tool_input"] != nil
          - set(span.attributes["input.mime_type"], "application/json") where (span.attributes["span.type"] == "tool" or span.name == "claude_code.tool") and span.attributes["tool_input"] != nil
          - set(span.attributes["openinference.span.kind"], "TOOL") where span.attributes["span.type"] == "tool" or span.name == "claude_code.tool"
          - set(span.name, Concat(["execute_tool ", span.attributes["tool_name"]], "")) where (span.attributes["span.type"] == "tool" or span.name == "claude_code.tool") and span.attributes["tool_name"] != nil
      - context: span
        statements:
          - set(span.attributes["output.value"], resource.attributes["{GALILEO_OUTPUT_SCRATCH_ATTRIBUTE}"]) where (span.attributes["span.type"] == "interaction" or span.name == "claude_code.interaction") and resource.attributes["{GALILEO_OUTPUT_SCRATCH_ATTRIBUTE}"] != nil
          - set(span.attributes["output.mime_type"], "text/plain") where (span.attributes["span.type"] == "interaction" or span.name == "claude_code.interaction") and resource.attributes["{GALILEO_OUTPUT_SCRATCH_ATTRIBUTE}"] != nil
          - set(span.attributes["gen_ai.response.content"], resource.attributes["{GALILEO_OUTPUT_SCRATCH_ATTRIBUTE}"]) where (span.attributes["span.type"] == "interaction" or span.name == "claude_code.interaction") and resource.attributes["{GALILEO_OUTPUT_SCRATCH_ATTRIBUTE}"] != nil
      - context: resource
        statements:
          - delete_key(resource.attributes, "{GALILEO_OUTPUT_SCRATCH_ATTRIBUTE}")
  # Keep only the logical interaction, LLM request, and parent tool spans in
  # Galileo. Permission/execution timing children stay in Splunk but would appear
  # as duplicate generic agents in Galileo and make tool metrics ineligible.
  filter/claude_code_galileo_genai:
    error_mode: ignore
    traces:
      span:
        - span.attributes["span.type"] == "tool.execution"
        - span.attributes["span.type"] == "tool.blocked_on_user"
        - span.attributes["span.type"] == "hook"
        - span.attributes["gen_ai.operation.name"] == nil and span.attributes["gen_ai.system"] == nil and span.attributes["gen_ai.request.model"] == nil and span.attributes["gen_ai.tool.call.id"] == nil
  filter/claude_code_token_metrics:
    error_mode: ignore
    metrics:
      metric:
        - metric.name != "claude_code.token.usage"
  # Claude Code's reliable token counts are native metrics, not always span
  # attributes. Convert claude_code.token.usage into the GenAI token metric the
  # Splunk AI overview reads, and export it through OTLP metric ingest so
  # sf_environment/sf_service are preserved.
  transform/claude_code_token_metric_genai:
    error_mode: ignore
    metric_statements:
      - context: metric
        statements:
          - set(metric.name, "gen_ai.client.token.usage") where metric.name == "claude_code.token.usage"
      - context: datapoint
        statements:
          - set(datapoint.attributes["gen_ai.agent.name"], {yaml_quote(service_name)}) where datapoint.attributes["gen_ai.agent.name"] == nil
          - set(datapoint.attributes["gen_ai.framework"], "claude-code") where datapoint.attributes["gen_ai.framework"] == nil
          - set(datapoint.attributes["gen_ai.operation.name"], "chat") where datapoint.attributes["gen_ai.operation.name"] == nil
          - set(datapoint.attributes["gen_ai.system"], "anthropic") where datapoint.attributes["gen_ai.system"] == nil
          - set(datapoint.attributes["gen_ai.request.model"], datapoint.attributes["model"]) where datapoint.attributes["gen_ai.request.model"] == nil and datapoint.attributes["model"] != nil
          - set(datapoint.attributes["gen_ai.token.type"], datapoint.attributes["type"]) where datapoint.attributes["gen_ai.token.type"] == nil and datapoint.attributes["type"] != nil
          - set(datapoint.attributes["gen_ai.token.type"], "input") where datapoint.attributes["type"] == "cacheRead" or datapoint.attributes["type"] == "cacheCreation"
{datapoint_provider_statements}
          - set(datapoint.attributes["aws.bedrock.inference_profile_arn"], datapoint.attributes["gen_ai.request.model"]) where datapoint.attributes["gen_ai.request.model"] != nil and IsMatch(datapoint.attributes["gen_ai.request.model"], "^arn:aws:bedrock:")
{datapoint_model_alias_statements}
          - set(datapoint.attributes["gen_ai.response.model"], datapoint.attributes["gen_ai.request.model"]) where datapoint.attributes["gen_ai.response.model"] == nil and datapoint.attributes["gen_ai.request.model"] != nil
  # Claude defaults to delta temporality, but older/overridden profiles can emit
  # cumulative token sums. Normalize cumulative input before histogram observation;
  # delta input passes through unchanged.
  cumulativetodelta/claude_code_tokens:
    include:
      match_type: strict
      metrics:
        - gen_ai.client.token.usage

connectors:
  # Produce the GenAI operation-duration histogram that Splunk AI Agent
  # Monitoring expects for latency charts. The namespace makes the connector's
  # duration metric land as gen_ai.client.operation.duration.
  span_metrics/claude_code_genai:
    namespace: gen_ai.client.operation
    histogram:
      unit: s
      explicit:
        buckets: [0.01, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64, 1.28, 2.56, 5.12, 10.24, 20.48, 40.96, 81.92]
    dimensions:
      - name: gen_ai.agent.name
      - name: gen_ai.framework
      - name: gen_ai.system
      - name: gen_ai.request.model
      - name: gen_ai.response.model
      - name: gen_ai.provider.name
      - name: gen_ai.operation.name
  # Splunk AI Agent Monitoring requires gen_ai.client.token.usage to be a
  # histogram. Observe each normalized token increment
  # and retain the GenAI dimensions used by the Tokens and Cost views.
  signal_to_metrics/claude_code_token_histogram:
    error_mode: ignore
    datapoints:
      - name: gen_ai.client.token.usage
        description: Number of input and output tokens used by GenAI clients
        unit: "{{token}}"
        conditions:
          - metric.name == "gen_ai.client.token.usage"
        attributes:
          - key: gen_ai.token.type
          - key: gen_ai.agent.name
          - key: gen_ai.framework
          - key: gen_ai.system
          - key: gen_ai.request.model
          - key: gen_ai.response.model
          - key: gen_ai.provider.name
          - key: gen_ai.operation.name
          - key: aws.bedrock.inference_profile_arn
        histogram:
          buckets: [1, 4, 16, 64, 256, 1024, 4096, 16384, 65536, 262144, 1048576, 4194304, 16777216, 67108864]
          count: "1"
          value: Double(datapoint.value_int) + datapoint.value_double

exporters:
  otlp_http/claude_code_traces:
    traces_endpoint: {yaml_quote(f"https://ingest.{realm}.observability.splunkcloud.com/v2/trace/otlp")}
    headers:
      X-SF-TOKEN: "${{env:SPLUNK_ACCESS_TOKEN}}"
  otlp_http/claude_code_metrics:
    metrics_endpoint: {yaml_quote(f"https://ingest.{realm}.observability.splunkcloud.com/v2/datapoint/otlp")}
    headers:
      X-SF-TOKEN: "${{env:SPLUNK_ACCESS_TOKEN}}"
  otlp_http/claude_code_logs:
    logs_endpoint: {yaml_quote(f"https://ingest.{realm}.observability.splunkcloud.com/v2/log/otlp")}
    headers:
      X-SF-TOKEN: "${{env:SPLUNK_ACCESS_TOKEN}}"
  signalfx/claude_code:
    realm: {yaml_quote(realm)}
    access_token: "${{env:SPLUNK_ACCESS_TOKEN}}"
    send_otlp_histograms: true
{galileo_block}
service:
  pipelines:
    traces/claude_code:
      receivers: [otlp/claude_code]
      processors: [resource/claude_code, transform/claude_code_genai, batch/claude_code]
      exporters: [{", ".join(trace_exporters)}]
{'''    traces/claude_code_galileo:
      receivers: [otlp/claude_code]
      processors: [resource/claude_code, transform/claude_code_genai, transform/claude_code_galileo, filter/claude_code_galileo_genai, batch/claude_code]
      exporters: [otlp_http/galileo]
''' if galileo_enabled else ""}
    metrics/claude_code_genai_duration:
      receivers: [span_metrics/claude_code_genai]
      processors: [batch/claude_code]
      exporters: [otlp_http/claude_code_metrics]
    metrics/claude_code:
      receivers: [otlp/claude_code]
      processors: [resource/claude_code, batch/claude_code]
      exporters: [signalfx/claude_code]
    logs/claude_code:
      receivers: [otlp/claude_code]
      processors: [resource/claude_code, batch/claude_code]
      exporters: [otlp_http/claude_code_logs]
    metrics/claude_code_token_genai:
      receivers: [otlp/claude_code]
      processors: [resource/claude_code, filter/claude_code_token_metrics, transform/claude_code_token_metric_genai, cumulativetodelta/claude_code_tokens, batch/claude_code]
      exporters: [signal_to_metrics/claude_code_token_histogram]
    metrics/claude_code_token_histogram:
      receivers: [signal_to_metrics/claude_code_token_histogram]
      processors: [batch/claude_code]
      exporters: [otlp_http/claude_code_metrics]
"""


def render_shared_collector_routing_reference(config: dict[str, Any]) -> str:
    cc = config["claude_code"]
    service_name = str(cc.get("service_name") or "claude-code")
    environment = str(cc.get("environment") or "claude-code")
    return f"""# Shared Collector Routing for Claude Code

Use this pattern when Claude Code shares one OTLP receiver with Codex or other
agents. Claude Code can put `service.name=claude-code` and `data.source=claude-code`
on spans and metric datapoints instead of the OTLP resource envelope. Resource-only
routes can silently send real Claude spans to the default pipeline, which prevents
`transform/claude_code_genai` from running and leaves the Splunk AI overview empty.

For a Docker collector, keep Claude's host-side endpoint at
`http://127.0.0.1:14318`, publish `127.0.0.1:14318:4318`, and bind the existing
container receiver to `0.0.0.0:4318`. The host endpoint is a client address; it
is not a valid container-internal receiver bind address.

```yaml
connectors:
  routing/claude_code_traces:
    default_pipelines: [traces/default]
    error_mode: ignore
    table:
      - context: span
        condition: 'attributes["data.source"] == "claude-code" or attributes["service.name"] == "{service_name}" or IsMatch(name, "^claude_code\\\\.")'
        pipelines: [traces/claude_code]
  routing/claude_code_metrics:
    default_pipelines: [metrics/default]
    error_mode: ignore
    table:
      - context: metric
        condition: 'name == "claude_code.token.usage"'
        pipelines: [metrics/claude_code, metrics/claude_code_token_genai]
      - context: metric
        condition: 'IsMatch(name, "^claude_code\\\\.")'
        pipelines: [metrics/claude_code]
      - context: datapoint
        condition: 'attributes["data.source"] == "claude-code" or attributes["service.name"] == "{service_name}"'
        pipelines: [metrics/claude_code]
  routing/claude_code_logs:
    default_pipelines: [logs/default]
    error_mode: ignore
    table:
      - context: log
        condition: 'attributes["data.source"] == "claude-code" or attributes["service.name"] == "{service_name}" or (attributes["event.name"] != nil and IsMatch(attributes["event.name"], "^claude_code\\."))'
        pipelines: [logs/claude_code]
  span_metrics/claude_code_genai:
    namespace: gen_ai.client.operation
    histogram:
      unit: s
      explicit:
        buckets: [0.01, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64, 1.28, 2.56, 5.12, 10.24, 20.48, 40.96, 81.92]
    dimensions:
      - name: gen_ai.agent.name
      - name: gen_ai.framework
      - name: gen_ai.system
      - name: gen_ai.request.model
      - name: gen_ai.response.model
      - name: gen_ai.provider.name
      - name: gen_ai.operation.name
  signal_to_metrics/claude_code_token_histogram:
    error_mode: ignore
    datapoints:
      - name: gen_ai.client.token.usage
        description: Number of input and output tokens used by GenAI clients
        unit: "{{token}}"
        conditions:
          - metric.name == "gen_ai.client.token.usage"
        attributes:
          - key: gen_ai.token.type
          - key: gen_ai.agent.name
          - key: gen_ai.framework
          - key: gen_ai.system
          - key: gen_ai.request.model
          - key: gen_ai.response.model
          - key: gen_ai.provider.name
          - key: gen_ai.operation.name
          - key: aws.bedrock.inference_profile_arn
        histogram:
          buckets: [1, 4, 16, 64, 256, 1024, 4096, 16384, 65536, 262144, 1048576, 4194304, 16777216, 67108864]
          count: "1"
          value: Double(datapoint.value_int) + datapoint.value_double

processors:
  resource/claude_code:
    attributes:
      - key: service.name
        value: {service_name}
        action: upsert
      - key: deployment.environment.name
        value: {environment}
        action: upsert
      - key: deployment.environment
        value: {environment}
        action: upsert
      - key: sf_environment
        value: {environment}
        action: upsert
      - key: sf_service
        value: {service_name}
        action: upsert
  cumulativetodelta/claude_code_tokens:
    include:
      match_type: strict
      metrics:
        - gen_ai.client.token.usage

service:
  pipelines:
    traces/in:
      receivers: [otlp]
      exporters: [routing/claude_code_traces]
    metrics/in:
      receivers: [otlp]
      exporters: [routing/claude_code_metrics]
    logs/in:
      receivers: [otlp]
      exporters: [routing/claude_code_logs]
    traces/claude_code:
      receivers: [routing/claude_code_traces]
      processors: [resource/claude_code, transform/claude_code_genai, batch]
      exporters: [otlp_http/claude_code_traces, span_metrics/claude_code_genai]
    metrics/claude_code_genai_duration:
      receivers: [span_metrics/claude_code_genai]
      processors: [batch]
      exporters: [otlp_http/claude_code_metrics]
    metrics/claude_code:
      receivers: [routing/claude_code_metrics]
      processors: [resource/claude_code, batch]
      exporters: [signalfx/claude_code]
    metrics/claude_code_token_genai:
      receivers: [routing/claude_code_metrics]
      processors: [resource/claude_code, filter/claude_code_token_metrics, transform/claude_code_token_metric_genai, cumulativetodelta/claude_code_tokens, batch]
      exporters: [signal_to_metrics/claude_code_token_histogram]
    metrics/claude_code_token_histogram:
      receivers: [signal_to_metrics/claude_code_token_histogram]
      processors: [batch]
      exporters: [otlp_http/claude_code_metrics]
    logs/claude_code:
      receivers: [routing/claude_code_logs]
      processors: [resource/claude_code, batch]
      exporters: [signalfx/claude_code]
```

The required pieces are the `span`, `metric`, `datapoint`, and `log` routing
contexts above plus the `transform/claude_code_genai` processor in the Claude
trace pipeline before `batch`, and the native-token
`filter/claude_code_token_metrics` + `transform/claude_code_token_metric_genai`
processors followed by `cumulativetodelta/claude_code_tokens` in the Claude
GenAI token metric pipeline before `batch`. Export that pipeline to
`signal_to_metrics/claude_code_token_histogram`, then receive the connector in
`metrics/claude_code_token_histogram` and export it to
`otlp_http/claude_code_metrics`. Export the transformed trace pipeline to
`span_metrics/claude_code_genai` and then to `otlp_http/claude_code_metrics` so
Splunk AI Agent Monitoring receives both required histogram metrics.
"""


def render_headers_helper(config: dict[str, Any], destination: str) -> str:
    if destination == "external-collector":
        header_env = external_dynamic_headers(config)
        literal_headers = {
            str(key): str(value)
            for key, value in (config["claude_code"].get("external_headers") or {}).items()
            if not ENV_PLACEHOLDER_LOCAL_RE.fullmatch(str(value))
        }
        return f"""#!/usr/bin/env bash
# Claude Code otelHeadersHelper for an external OTLP/HTTP collector.
# Placeholder-backed values are resolved from the Claude process environment;
# no credential value is persisted in settings.json or this script.
set -euo pipefail

python3 <<'PY'
import json
import os
import sys

header_env = {json.dumps(header_env, sort_keys=True)}
headers = {json.dumps(literal_headers, sort_keys=True)}
missing = []
for header, env_name in header_env.items():
    value = os.environ.get(env_name, "")
    if value:
        headers[header] = value
    else:
        missing.append(env_name)

if missing:
    print(
        "claude-code-otel-headers: missing environment variable(s): "
        + ", ".join(sorted(missing)),
        file=sys.stderr,
    )
print(json.dumps(headers))
PY
"""

    return """#!/usr/bin/env bash
# Claude Code otelHeadersHelper: emits OTLP headers as JSON at runtime.
# Reads the Splunk Observability access token from a chmod 600 file so the
# token value never appears on argv, environment variable exports, or in
# .claude/settings.json.
set -euo pipefail

log_error() {
  printf '%s\\n' "$1" >&2
}

emit_empty() {
  printf '%s\\n' '{}'
  exit 0
}

token_file="${SPLUNK_O11Y_TOKEN_FILE:-}"
if [[ -z "${token_file}" ]]; then
  token_file="${HOME}/.splunk-o11y-token"
fi

if [[ ! -f "${token_file}" ]]; then
  log_error "claude-code-otel-headers: token file not found: ${token_file}"
  emit_empty
fi

python3 - "${token_file}" <<'PY'
import json
import sys
from pathlib import Path

try:
    header_value = Path(sys.argv[1]).read_text(encoding="utf-8").strip()
except OSError:
    print("{}")
    raise SystemExit(0)

if not header_value:
    print("{}")
    raise SystemExit(0)

print(json.dumps({"X-SF-TOKEN": header_value}))
PY
"""


def render_galileo_handoff(config: dict[str, Any]) -> str:
    cc = config["claude_code"]
    galileo_enabled = bool_config(cc.get("galileo_enabled"))
    galileo_project = str(cc.get("galileo_project") or "<project-name>")
    galileo_log_stream = str(cc.get("galileo_log_stream") or "default")
    galileo_endpoint = str(cc.get("galileo_otel_endpoint") or "<not-configured>")
    galileo_console_url = str(cc.get("galileo_console_url") or "")
    destination = str(cc.get("destination"))
    api_base = (
        re.sub(r"/otel(?:/v1)?/traces/?$", "", galileo_endpoint.rstrip("/"))
        if galileo_endpoint.startswith("https://")
        else "<galileo-api-base>"
    )
    platform_cmd = [
        "bash skills/galileo-platform-setup/scripts/setup.sh --render \\",
        f"  --project-name {shell_quote(galileo_project)} \\",
        f"  --log-stream {shell_quote(galileo_log_stream)} \\",
        f"  --metrics {shell_quote(','.join(GALILEO_CODING_AGENT_METRICS))} \\",
    ]
    if galileo_console_url:
        platform_cmd.append(f"  --galileo-console-url {shell_quote(galileo_console_url)}")
    elif galileo_endpoint.startswith("https://"):
        platform_cmd.append(f"  --galileo-otel-endpoint {shell_quote(galileo_endpoint)}")
    else:
        platform_cmd.append("  --galileo-console-url '<ask-user-for-instance-url>'")
    lines = [
        "# Claude Code -> Galileo Handoff",
        "",
        f"- Galileo integration enabled: `{str(galileo_enabled).lower()}`",
        f"- Galileo project: `{galileo_project}`",
        f"- Galileo log stream: `{galileo_log_stream}`",
        f"- Galileo OTLP endpoint: `{galileo_endpoint}`",
        f"- Destination: `{destination}`",
        "",
        "## Fan-out Pattern",
        "",
        "Claude Code emits OTel signals to the local collector at",
        f"`{cc.get('local_collector_endpoint', 'http://127.0.0.1:14318')}`. The rendered",
        "collector overlay exports:",
        "",
        "- Traces to Splunk Observability Cloud (`otlp_http/claude_code_traces`) and",
        "  optionally to Galileo (`otlp_http/galileo`).",
        "- Metrics to Splunk Observability Cloud via `signalfx/claude_code`.",
        "- Logs to Splunk Observability Cloud via `otlp_http/claude_code_logs`.",
        "",
        "Galileo receives only traces because Galileo Observe ingests OTLP/HTTP traces.",
        "",
        "## Provisioning a Galileo Project + Log Stream",
        "",
        "Hand off to `galileo-platform-setup` to create the target project and log",
        "stream and to configure retention, RBAC, scorers, and metrics:",
        "",
        "```bash",
        *platform_cmd,
        "```",
        "",
        "## API Key File",
        "",
        "Create the API key file without exposing it on the command line:",
        "",
        "```bash",
        "bash skills/shared/scripts/write_secret_file.sh ~/.galileo-api-key",
        "chmod 600 ~/.galileo-api-key",
        "```",
        "",
        "Reference it from the collector environment as `GALILEO_API_KEY` (for example",
        "via `direnv`, systemd `EnvironmentFile`, or Kubernetes secret material). The",
        "collector overlay resolves the header as `${env:GALILEO_API_KEY}` so the raw",
        "value stays out of rendered files.",
        "",
        "## Direct REST Fallback",
        "",
        "If the collector fan-out is unavailable, Claude Code turns can be posted",
        "directly to Galileo via:",
        "",
        "```",
        f"POST {api_base}/v2/projects/{{project_id}}/traces",
        "Content-Type: application/json",
        "Galileo-API-Key: <api key>",
        "",
        "{",
        "  \"logging_method\": \"api_direct\",",
        "  \"reliable\": true,",
        "  \"records\": [ ... ]",
        "}",
        "```",
        "",
        "The Splunk O11y trace path remains authoritative; Galileo is a companion",
        "destination for agent-trace evaluation and scoring.",
    ]
    return "\n".join(lines) + "\n"


def render_runtime_env(config: dict[str, Any], output_dir: Path) -> str:
    cc = config["claude_code"]
    destination = str(cc["destination"])
    scope = str(cc.get("settings_scope", "user"))
    return f"""# Source this file to expose Claude Code O11y runtime paths.
export CLAUDE_CODE_O11Y_RENDERED_DIR={shell_quote(str(output_dir))}
export CLAUDE_CODE_O11Y_DESTINATION={shell_quote(destination)}
export CLAUDE_CODE_O11Y_SETTINGS_SCOPE={shell_quote(scope)}
# Provide SPLUNK_O11Y_TOKEN_FILE (chmod 600) for the otelHeadersHelper.
# Provide GALILEO_API_KEY (or GALILEO_API_KEY_FILE + wrapper) for the collector.
# Do not place token values in this file.
"""


def apply_plan(config: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    cc = config["claude_code"]
    destination = str(cc["destination"])
    scope = str(cc.get("settings_scope", "user"))
    galileo_enabled = bool_config(cc.get("galileo_enabled"))
    settings_target = resolve_settings_scope_path(config, output_dir)

    steps: list[dict[str, Any]] = []
    settings_commands: list[list[str]] = []
    for name in destinations_for(destination):
        source = output_dir / "settings" / f"claude-settings.{scope}.{name}.json"
        settings_commands.append(["merge-settings", str(source), str(settings_target)])
    steps.append(
        {
            "section": "settings",
            "action": "merge managed Claude Code settings.json env block",
            "commands": settings_commands,
        }
    )

    env_commands: list[list[str]] = []
    for name in destinations_for(destination):
        env_source = output_dir / "env" / f"claude-code-o11y.{name}.env"
        env_target = str(Path.home() / ".claude" / f"claude-code-o11y.{name}.env")
        env_commands.append(["install", "-m", "0644", str(env_source), env_target])
    if any(
        destination_uses_headers_helper(config, name)
        for name in destinations_for(destination)
    ):
        helper_source = output_dir / "bin" / "claude-code-otel-headers.sh"
        helper_target = str(headers_helper_target_path(config, output_dir))
        env_commands.append(["install-executable", "-m", "0755", str(helper_source), helper_target])
    steps.append(
        {
            "section": "env-helper",
            "action": "install shell env helper and direct-mode headers helper for token placeholders",
            "commands": env_commands,
        }
    )

    collector_commands: list[list[str]] = []
    if destination in {"local-collector", "all"}:
        collector_source = output_dir / "collector" / "claude-code-o11y-local-collector.yaml"
        collector_target = str(output_dir / "collector" / "claude-code-o11y-local-collector.yaml")
        collector_commands.append(["render-only", str(collector_source), collector_target])
    steps.append(
        {
            "section": "collector-overlay",
            "action": "publish local-collector overlay for collector-managed fan-out",
            "commands": collector_commands,
        }
    )

    steps.append(
        {
            "section": "galileo-handoff",
            "action": "review Galileo handoff and provision project via galileo-platform-setup",
            "commands": [["source", str(output_dir / "runtime" / "galileo-handoff.md")]],
        }
    )

    return {
        "generated_at": now_iso(),
        "skill": SKILL_NAME,
        "settings_target": str(settings_target),
        "destination": destination,
        "settings_scope": scope,
        "galileo_enabled": galileo_enabled,
        "steps": steps,
        "direct_secrets_rendered": False,
    }


def coverage_report(config: dict[str, Any]) -> dict[str, Any]:
    cc = config["claude_code"]
    destination = str(cc["destination"])
    traces_enabled = bool_config(cc.get("enable_traces_beta"))
    galileo_enabled = bool_config(cc.get("galileo_enabled"))
    if not galileo_enabled:
        galileo_status = "not_applicable"
    elif destination == "external-collector":
        galileo_status = "operator_owned"
    elif destination == "splunk-direct":
        galileo_status = "not_applicable"
    else:
        galileo_status = "render"
    entries = [
        {
            "key": "claude_code.settings_env_block",
            "status": "render",
            "summary": "Native Claude Code OTel is configured via the .claude/settings.json env block per docs.",
            "source_url": "https://code.claude.com/docs/en/monitoring-usage",
        },
        {
            "key": "claude_code.metrics",
            "status": "render",
            "summary": "OTEL_METRICS_EXPORTER=otlp enables metric export at the configured interval.",
            "source_url": "https://code.claude.com/docs/en/monitoring-usage",
        },
        {
            "key": "claude_code.logs",
            "status": "render",
            "summary": "OTEL_LOGS_EXPORTER=otlp enables the structured Claude Code log stream.",
            "source_url": "https://code.claude.com/docs/en/monitoring-usage",
        },
        {
            "key": "claude_code.traces_beta",
            "status": "render" if traces_enabled else "not_applicable",
            "summary": "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1 plus OTEL_TRACES_EXPORTER=otlp enables trace export.",
            "source_url": "https://code.claude.com/docs/en/monitoring-usage",
        },
        {
            "key": "claude_code.detailed_traces",
            "status": "render" if (traces_enabled and bool_config(cc.get("enable_detailed_traces"))) else "not_applicable",
            "summary": (
                "ENABLE_BETA_TRACING_DETAILED=1 + BETA_TRACING_ENDPOINT add hook spans and "
                "experimental attributes. Current base beta tracing already emits llm_request and tool spans."
            ),
            "source_url": "https://code.claude.com/docs/en/monitoring-usage",
        },
        {
            "key": "splunk.direct_otlp_http",
            "status": "render" if destination in {"splunk-direct", "all"} else "not_applicable",
            "summary": "Direct Splunk ingest uses per-signal OTLP/HTTP endpoints and X-SF-TOKEN via otelHeadersHelper.",
            "source_url": "https://dev.splunk.com/observability/reference/api/ingest_data/latest",
        },
        {
            "key": "splunk.collector_overlay",
            "status": "render" if destination in {"local-collector", "all"} else ("operator_owned" if destination == "external-collector" else "not_applicable"),
            "summary": "Local overlay fans Claude Code OTel out to Splunk O11y and optional Galileo, and requires a collector build with signal_to_metrics for the token histogram; external collector mode is operator-owned.",
            "source_url": "https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/connector/signaltometricsconnector",
        },
        {
            "key": "splunk.histograms",
            "status": "render" if destination in {"local-collector", "all"} else "not_applicable",
            "summary": "Collector overlay emits GenAI duration and token histograms and enables OTLP histogram transport.",
            "source_url": "https://help.splunk.com/en/splunk-observability-cloud/manage-data/metrics-metadata-and-events/metrics-events-and-metadata/get-histogram-data-in",
        },
        {
            "key": "galileo.traces",
            "status": galileo_status,
            "summary": (
                "Galileo Observe ingests Claude Code traces via otlp_http/galileo when the local collector "
                "fan-out is rendered; external collector Galileo fan-out is operator-owned."
            ),
            "source_url": "https://docs.galileo.ai/how-to-guides/third-party-integrations/otel",
        },
        {
            "key": "galileo.genai_attributes",
            "status": galileo_status,
            "summary": (
                "Galileo /otel/traces only ingests spans that carry OTel GenAI semantic-convention "
                "attributes (gen_ai.*). Claude Code llm_request spans satisfy this; spans without "
                "gen_ai.* are rejected with partialSuccess 'No GenAI patterns detected in spans'."
            ),
            "source_url": "https://docs.galileo.ai/how-to-guides/third-party-integrations/otel",
        },
        {
            "key": "galileo.non_public_tenant",
            "status": galileo_status,
            "summary": (
                "Every Galileo-enabled run requires the user-confirmed instance URL. Public app.galileo.ai, "
                "console. hosts, and console- hosts are mapped to their documented API forms; keys remain tenant-bound."
            ),
            "source_url": "https://docs.galileo.ai/how-to-guides/third-party-integrations/otel",
        },
        {
            "key": "content_capture",
            "status": "render" if bool_config(cc.get("accept_content_capture")) else "render_disabled",
            "summary": "Prompt, response, tool, and raw API body capture are gated behind --accept-content-capture.",
            "source_url": "https://code.claude.com/docs/en/monitoring-usage",
        },
    ]
    return {"generated_at": now_iso(), "coverage": entries}


def coverage_markdown(coverage: dict[str, Any]) -> str:
    lines = ["# Coverage Report", "", "| Key | Status | Summary |", "|---|---|---|"]
    for entry in coverage.get("coverage", []):
        lines.append(f"| `{entry['key']}` | `{entry['status']}` | {entry['summary']} |")
    return "\n".join(lines) + "\n"


def doctor_report(config: dict[str, Any], errors: list[str], warnings: list[str]) -> str:
    cc = config["claude_code"]
    lines = [
        "# Claude Code O11y Doctor Report",
        "",
        f"Generated: `{now_iso()}`",
        "",
        "## Destination",
        "",
        f"- Selected destination: `{cc['destination']}`",
        f"- Settings scope: `{cc.get('settings_scope', 'user')}`",
        f"- Traces beta enabled: `{str(bool_config(cc.get('enable_traces_beta'))).lower()}`",
        f"- Galileo enabled: `{str(bool_config(cc.get('galileo_enabled'))).lower()}`",
        f"- Content capture accepted: `{str(bool_config(cc.get('accept_content_capture'))).lower()}`",
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
            "- Copy or merge the rendered settings JSON into the target `.claude/settings.json`.",
            "- For splunk-direct, install the otelHeadersHelper script and set `SPLUNK_O11Y_TOKEN_FILE`.",
            "- For local-collector, use a collector build with signal_to_metrics (validated: otel/opentelemetry-collector-contrib:0.154.0) and merge the overlay.",
            "- For Galileo fan-out, use the user-confirmed instance URL, provision the project/log stream via `galileo-platform-setup`, and export `GALILEO_API_KEY`.",
        ]
    )
    return "\n".join(lines) + "\n"


def render_handoff(config: dict[str, Any], output_dir: Path) -> str:
    cc = config["claude_code"]
    destination = str(cc["destination"])
    lines = [
        "# Claude Code O11y Handoff",
        "",
        "## Settings Install",
        "",
        "Merge the rendered `settings/claude-settings.<scope>.<destination>.json` into",
        "your Claude Code `.claude/settings.json`. Only keys owned by this skill",
        "(`CLAUDE_CODE_*`, `OTEL_*` env keys, plus `otelHeadersHelper`) are managed.",
        "",
        "## Env Helper",
        "",
        "Source `env/claude-code-o11y.<destination>.env` in your shell to expose the",
        "managed env vars for ad hoc validation. Claude Code reads settings.json on",
        "start and does not require the env helper at runtime.",
        "",
        "## Destination",
        "",
        f"- Selected: `{destination}`",
        "",
    ]
    if destination in {"local-collector", "all"}:
        lines.extend(
            [
                "## Local Collector Overlay",
                "",
                "Merge `collector/claude-code-o11y-local-collector.yaml` into a collector",
                "gateway that includes the `signal_to_metrics` connector (validated:",
                "`otel/opentelemetry-collector-contrib:0.154.0`). The stock Splunk",
                "Distribution v0.154.2 omits that connector and cannot emit the required",
                "GenAI token histogram. Fan Claude Code traces to Splunk O11y and Galileo",
                "when enabled, then start the collector before a new Claude process.",
                "For Docker, publish `127.0.0.1:14318:4318` and bind the container's",
                "existing OTLP receiver to `0.0.0.0:4318`; keep Claude pointed at the",
                "host-side `http://127.0.0.1:14318` endpoint.",
                "If the gateway is shared with Codex or another agent, use",
                "`runtime/shared-collector-routing.md` so routes match Claude span",
                "and datapoint attributes, not only resource attributes.",
                "Run `validate.sh --collector-config <merged-config>` before restart.",
                "",
            ]
        )
    if destination == "external-collector":
        lines.extend(
            [
                "## External Collector",
                "",
                "No collector overlay is rendered. Claude Code settings point at the",
                "operator-owned OTLP collector endpoint(s).",
                "",
            ]
        )
    if destination in {"splunk-direct", "all"}:
        lines.extend(
            [
                "## Splunk Direct Headers Helper",
                "",
                "Install `bin/claude-code-otel-headers.sh` at a stable path and point the",
                "settings.json `otelHeadersHelper` key at it. The helper reads",
                "`SPLUNK_O11Y_TOKEN_FILE` (chmod 600) and emits the required",
                "`X-SF-TOKEN` header at runtime so the token never lives in settings.json.",
                "",
            ]
        )
    if destination == "external-collector" and destination_uses_headers_helper(
        config, destination
    ):
        lines.extend(
            [
                "## External Collector Headers Helper",
                "",
                "Install `bin/claude-code-otel-headers.sh` at the rendered path.",
                "It resolves placeholder-backed OTLP/HTTP headers from runtime",
                "environment variables; export those variables before starting Claude Code.",
                "",
            ]
        )
    lines.extend(
        [
            "## Galileo",
            "",
            "See `runtime/galileo-handoff.md` for project provisioning, key file setup,",
            "and how Galileo receives traces via the collector fan-out.",
        ]
    )
    return "\n".join(lines) + "\n"


def render(config: dict[str, Any], output_dir: Path, json_output: bool = False) -> dict[str, Any]:
    errors, warnings = validate_config(config)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Validate BEFORE wiping prior output so a failed render does not destroy a
    # previously-good rendered tree (and leave a stale apply-plan.json behind).
    if errors:
        metadata = {"ok": False, "errors": errors, "warnings": warnings, "generated_at": now_iso()}
        write_json(output_dir / "metadata.json", metadata)
        write_text(output_dir / "doctor-report.md", doctor_report(config, errors, warnings))
        if json_output:
            print(json.dumps(metadata, indent=2, sort_keys=True))
        raise UsageError("; ".join(errors))

    for child in ("settings", "env", "collector", "bin", "runtime"):
        target = output_dir / child
        if target.exists():
            shutil.rmtree(target)

    cc = config["claude_code"]
    scope = str(cc.get("settings_scope", "user"))
    destination = str(cc["destination"])
    rendered_settings: list[str] = []
    for name in destinations_for(destination):
        settings_text = render_settings_file(config, name, output_dir)
        json.loads(settings_text)
        settings_path = output_dir / "settings" / f"claude-settings.{scope}.{name}.json"
        write_text(settings_path, settings_text)
        rendered_settings.append(settings_path.relative_to(output_dir).as_posix())
        env_text = render_env_file(config, name, output_dir)
        write_text(output_dir / "env" / f"claude-code-o11y.{name}.env", env_text)

    if destination in {"local-collector", "all"}:
        write_text(
            output_dir / "collector" / "claude-code-o11y-local-collector.yaml",
            render_collector_overlay(config),
        )
    helper_destination = next(
        (
            name
            for name in destinations_for(destination)
            if destination_uses_headers_helper(config, name)
        ),
        "",
    )
    if helper_destination:
        write_text(
            output_dir / "bin" / "claude-code-otel-headers.sh",
            render_headers_helper(config, helper_destination),
            executable=True,
        )

    write_text(output_dir / "runtime" / "galileo-handoff.md", render_galileo_handoff(config))
    write_text(output_dir / "runtime" / "shared-collector-routing.md", render_shared_collector_routing_reference(config))
    write_text(output_dir / "runtime" / "claude-code-o11y.env", render_runtime_env(config, output_dir))

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
        "rendered_settings": rendered_settings,
        "destination": destination,
        "settings_scope": scope,
        "galileo_enabled": bool_config(cc.get("galileo_enabled")),
        "direct_secrets_rendered": False,
        "errors": leak_errors,
        "warnings": warnings,
    }
    write_json(output_dir / "metadata.json", metadata)
    if leak_errors:
        raise UsageError("; ".join(leak_errors))
    return metadata


def _validate_overlay_structure_regex(text: str) -> list[str]:
    """PyYAML-free structural fallback. Confirms the traces pipeline exports to the
    Galileo exporter whenever otlp_http/galileo is defined, and that the core exporters
    are referenced. Used when PyYAML is not installed (the setup.sh shim runs the
    system python3, which may lack it)."""
    errors: list[str] = []
    galileo_defined = re.search(r"^\s*otlp_http/galileo:\s*$", text, re.MULTILINE) is not None
    galileo_trace_export = re.search(
        r"traces/[A-Za-z0-9_.-]+:\s*[\s\S]*?exporters:\s*\[[^\]]*otlp_http/galileo[^\]]*\]",
        text,
    )
    if galileo_defined and not galileo_trace_export:
        errors.append(
            "collector overlay defines otlp_http/galileo but no traces pipeline exports to it"
        )
    galileo_pipe = re.search(
        r"traces/[A-Za-z0-9_.-]*galileo[A-Za-z0-9_.-]*:\s*(?P<body>[\s\S]*?)(?:\n    [A-Za-z0-9_/.-]+:|\Z)",
        text,
    )
    if galileo_defined:
        if not galileo_pipe:
            errors.append("collector overlay defines otlp_http/galileo but no Galileo-specific traces pipeline")
        else:
            processors = re.search(r"processors:\s*\[([^\]]*)\]", galileo_pipe.group("body"))
            processor_text = processors.group(1) if processors else ""
            if "transform/claude_code_galileo" not in processor_text:
                errors.append("Galileo trace pipeline must run transform/claude_code_galileo")
            if "filter/claude_code_galileo_genai" not in processor_text:
                errors.append("Galileo trace pipeline must run filter/claude_code_galileo_genai")
            processor_list = [item.strip() for item in processor_text.split(",") if item.strip()]
            expected = (
                "transform/claude_code_genai",
                "transform/claude_code_galileo",
                "filter/claude_code_galileo_genai",
            )
            if all(component in processor_list for component in expected):
                indexes = [processor_list.index(component) for component in expected]
                if indexes != sorted(indexes):
                    errors.append(
                        "Galileo trace pipeline must normalize GenAI, map Galileo content, "
                        "then filter spans in that order"
                    )
    if re.search(r"context:\s*resource\b[\s\S]{0,240}pipelines:\s*\[[^\]]*traces/claude_code", text) and not re.search(
        r"context:\s*span\b[\s\S]{0,240}pipelines:\s*\[[^\]]*traces/claude_code", text
    ):
        errors.append(
            "shared collector Claude trace routing must include a context: span route; "
            "Claude Code often carries service.name/data.source on span attributes, not the resource"
        )
    if re.search(r"context:\s*resource\b[\s\S]{0,240}pipelines:\s*\[[^\]]*metrics/claude_code", text) and not re.search(
        r"context:\s*(?:metric|datapoint)\b[\s\S]{0,240}pipelines:\s*\[[^\]]*metrics/claude_code", text
    ):
        errors.append(
            "shared collector Claude metric routing must include context: metric or context: datapoint; "
            "Claude Code identity can be attached to metric names or datapoint attributes"
        )
    trace_pipe = re.search(
        r"^    traces/claude_code:\s*(?P<body>[\s\S]*?)(?=^    [A-Za-z0-9_/.-]+:|\Z)",
        text,
        re.MULTILINE,
    )
    if trace_pipe:
        body = trace_pipe.group("body")
        processors = re.search(r"processors:\s*\[([^\]]*)\]", body)
        if not processors or "transform/claude_code_genai" not in processors.group(1):
            errors.append("traces/claude_code pipeline must run transform/claude_code_genai")
        elif "batch/claude_code" in processors.group(1):
            processor_list = [item.strip() for item in processors.group(1).split(",")]
            if (
                "transform/claude_code_genai" in processor_list
                and "batch/claude_code" in processor_list
                and processor_list.index("transform/claude_code_genai") > processor_list.index("batch/claude_code")
            ):
                errors.append("traces/claude_code pipeline must run transform/claude_code_genai before batch/claude_code")
    token_pipe = re.search(
        r"^    metrics/claude_code_token_genai:\s*(?P<body>[\s\S]*?)(?=^    [A-Za-z0-9_/.-]+:|\Z)",
        text,
        re.MULTILINE,
    )
    token_histogram_pipe = re.search(
        r"^    metrics/claude_code_token_histogram:\s*(?P<body>[\s\S]*?)(?=^    [A-Za-z0-9_/.-]+:|\Z)",
        text,
        re.MULTILINE,
    )
    duration_pipe = re.search(
        r"^    metrics/claude_code_genai_duration:\s*(?P<body>[\s\S]*?)(?=^    [A-Za-z0-9_/.-]+:|\Z)",
        text,
        re.MULTILINE,
    )
    if "span_metrics/claude_code_genai" in text:
        if not trace_pipe or "span_metrics/claude_code_genai" not in trace_pipe.group("body"):
            errors.append("traces/claude_code pipeline must export to span_metrics/claude_code_genai")
        spanmetrics_block = re.search(
            r"^  span_metrics/claude_code_genai:\s*(?P<body>[\s\S]*?)(?=^  [A-Za-z0-9_/.-]+:\s*$|^exporters:|\Z)",
            text,
            re.MULTILINE,
        )
        if not spanmetrics_block or not re.search(r"^\s+unit:\s*s\s*$", spanmetrics_block.group("body"), re.MULTILINE):
            errors.append("span_metrics/claude_code_genai histogram must use unit s")
        if not duration_pipe:
            errors.append("collector overlay defines span_metrics/claude_code_genai but no metrics/claude_code_genai_duration pipeline")
        else:
            body = duration_pipe.group("body")
            receivers = re.search(r"receivers:\s*\[([^\]]*)\]", body)
            if not receivers or "span_metrics/claude_code_genai" not in receivers.group(1):
                errors.append("metrics/claude_code_genai_duration pipeline must receive from span_metrics/claude_code_genai")
            exporters = re.search(r"exporters:\s*\[([^\]]*)\]", body)
            if not exporters or "otlp_http/claude_code_metrics" not in exporters.group(1):
                errors.append("metrics/claude_code_genai_duration pipeline must export to otlp_http/claude_code_metrics")
    if "metrics/claude_code_genai_duration" in text and "namespace: gen_ai.client.operation" not in text:
        errors.append("span_metrics/claude_code_genai must use namespace gen_ai.client.operation")
    token_connector_name = GENAI_TOKEN_HISTOGRAM_CONNECTOR
    if "sum/claude_code_" in text:
        errors.append(
            "Claude token usage must not be exported by a sum connector; "
            "Splunk AI Agent Monitoring requires gen_ai.client.token.usage as a histogram"
        )
    if token_connector_name in text:
        token_connector = re.search(
            r"^  signal_to_metrics/claude_code_token_histogram:\s*(?P<body>[\s\S]*?)(?=^  [A-Za-z0-9_/.-]+:\s*$|^exporters:|\Z)",
            text,
            re.MULTILINE,
        )
        connector_body = token_connector.group("body") if token_connector else ""
        for required in (
            "name: gen_ai.client.token.usage",
            'unit: "{token}"',
            'metric.name == "gen_ai.client.token.usage"',
            "histogram:",
            'count: "1"',
            "Double(datapoint.value_int) + datapoint.value_double",
            "67108864",
        ):
            if required not in connector_body:
                errors.append(
                    "signal_to_metrics/claude_code_token_histogram missing required token histogram setting: "
                    + required
                )
        c2d = re.search(
            r"^  cumulativetodelta/claude_code_tokens:\s*(?P<body>[\s\S]*?)(?=^  [A-Za-z0-9_/.-]+:\s*$|^connectors:|\Z)",
            text,
            re.MULTILINE,
        )
        if not c2d or "gen_ai.client.token.usage" not in c2d.group("body"):
            errors.append(
                "cumulativetodelta/claude_code_tokens must include gen_ai.client.token.usage"
            )
    if "transform/claude_code_token_metric_genai" in text:
        if not token_pipe:
            errors.append("collector overlay defines transform/claude_code_token_metric_genai but no metrics/claude_code_token_genai pipeline")
        else:
            body = token_pipe.group("body")
            processors = re.search(r"processors:\s*\[([^\]]*)\]", body)
            processor_list = [item.strip() for item in processors.group(1).split(",")] if processors else []
            for required_processor in (
                "resource/claude_code",
                "filter/claude_code_token_metrics",
                "transform/claude_code_token_metric_genai",
                "cumulativetodelta/claude_code_tokens",
                "batch/claude_code",
            ):
                if required_processor not in processor_list:
                    errors.append(f"metrics/claude_code_token_genai pipeline must run {required_processor}")
            ordered = (
                "transform/claude_code_token_metric_genai",
                "cumulativetodelta/claude_code_tokens",
                "batch/claude_code",
            )
            if all(component in processor_list for component in ordered):
                indexes = [processor_list.index(component) for component in ordered]
                if indexes != sorted(indexes):
                    errors.append(
                        "metrics/claude_code_token_genai pipeline must run transform, "
                        "cumulativetodelta, then batch in that order"
                    )
            exporters = re.search(r"exporters:\s*\[([^\]]*)\]", body)
            if not exporters or token_connector_name not in exporters.group(1):
                errors.append(
                    "metrics/claude_code_token_genai pipeline must export to "
                    + token_connector_name
                )
            if exporters and "otlp_http/claude_code_metrics" in exporters.group(1):
                errors.append(
                    "metrics/claude_code_token_genai must not export the counter directly; "
                    "route it through " + token_connector_name
                )
    if token_connector_name in text:
        if not token_histogram_pipe:
            errors.append(
                "collector overlay defines signal_to_metrics/claude_code_token_histogram "
                "but no metrics/claude_code_token_histogram pipeline"
            )
        else:
            body = token_histogram_pipe.group("body")
            receivers = re.search(r"receivers:\s*\[([^\]]*)\]", body)
            if not receivers or token_connector_name not in receivers.group(1):
                errors.append(
                    "metrics/claude_code_token_histogram pipeline must receive from "
                    + token_connector_name
                )
            exporters = re.search(r"exporters:\s*\[([^\]]*)\]", body)
            if not exporters or "otlp_http/claude_code_metrics" not in exporters.group(1):
                errors.append(
                    "metrics/claude_code_token_histogram pipeline must export to otlp_http/claude_code_metrics"
                )
    if "metrics/claude_code_token_genai" in text and "transform/claude_code_token_metric_genai" not in text:
        errors.append("metrics/claude_code_token_genai pipeline must define transform/claude_code_token_metric_genai")
    if "metrics/claude_code_token_genai" in text and token_connector_name not in text:
        errors.append(
            "metrics/claude_code_token_genai pipeline must define " + token_connector_name
        )
    if "otlp_http/claude_code_metrics" in text and "/v2/datapoint/otlp" not in text:
        errors.append("otlp_http/claude_code_metrics must send to Splunk OTLP metric ingest /v2/datapoint/otlp")
    for required in (
        "gen_ai.operation.name",
        "SPAN_KIND_CLIENT",
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
        "gen_ai.response.model",
        "gen_ai.provider.name",
        "gen_ai.agent.name",
        "invoke_workflow",
        "gen_ai.workflow.name",
    ):
        if "transform/claude_code_genai" in text and required not in text:
            errors.append(f"transform/claude_code_genai missing required GenAI mapping: {required}")
    return errors


def _pipeline_refs(component: Any) -> list[str]:
    if isinstance(component, list):
        return [str(item) for item in component]
    return []


def _is_batch_component(name: str) -> bool:
    return name == "batch" or name.startswith("batch/")


def _has_exact_token_route(overlay: dict[str, Any]) -> bool:
    connectors = overlay.get("connectors") or {}
    if not isinstance(connectors, dict):
        return False
    for name, connector in connectors.items():
        if not str(name).startswith("routing") or not isinstance(connector, dict):
            continue
        for entry in connector.get("table") or []:
            if not isinstance(entry, dict):
                continue
            if "metrics/claude_code_token_genai" not in _pipeline_refs(entry.get("pipelines")):
                continue
            context = str(entry.get("context") or "resource")
            condition = str(entry.get("condition") or entry.get("statement") or "")
            if context in {"metric", "datapoint"} and "claude_code.token.usage" in condition:
                return True
    return False


def _splunk_metric_exporters(overlay: dict[str, Any]) -> set[str]:
    exporters = overlay.get("exporters") or {}
    if not isinstance(exporters, dict):
        return set()
    matches: set[str] = set()
    for name, exporter in exporters.items():
        if not isinstance(exporter, dict):
            continue
        endpoint = str(exporter.get("metrics_endpoint") or "")
        if endpoint.endswith("/v2/datapoint/otlp"):
            matches.add(str(name))
    return matches


def _validate_claude_shared_routing(overlay: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    connectors = overlay.get("connectors") or {}
    if not isinstance(connectors, dict):
        return errors

    trace_route_seen = False
    trace_span_route_seen = False
    metric_route_seen = False
    metric_record_route_seen = False
    token_route_seen = False
    exact_token_route_seen = False
    log_route_seen = False
    log_record_route_seen = False

    for connector_name, connector in connectors.items():
        if not str(connector_name).startswith("routing"):
            continue
        if not isinstance(connector, dict):
            continue
        table = connector.get("table") or []
        if not isinstance(table, list):
            continue
        for entry in table:
            if not isinstance(entry, dict):
                continue
            pipelines = _pipeline_refs(entry.get("pipelines"))
            context = str(entry.get("context") or "resource")
            if any(pipe == "traces/claude_code" for pipe in pipelines):
                trace_route_seen = True
                if context == "span":
                    trace_span_route_seen = True
            if any(pipe == "metrics/claude_code" or pipe.startswith("metrics/claude_code") for pipe in pipelines):
                metric_route_seen = True
                if context in {"metric", "datapoint"}:
                    metric_record_route_seen = True
            if "metrics/claude_code_token_genai" in pipelines:
                token_route_seen = True
                condition = str(entry.get("condition") or entry.get("statement") or "")
                if context in {"metric", "datapoint"} and "claude_code.token.usage" in condition:
                    exact_token_route_seen = True
            if any(pipe == "logs/claude_code" for pipe in pipelines):
                log_route_seen = True
                if context == "log":
                    log_record_route_seen = True

    if trace_route_seen and not trace_span_route_seen:
        errors.append(
            "shared collector Claude trace routing must include a context: span route; "
            "resource-only service.name/data.source routes miss real Claude Code llm_request spans"
        )
    if metric_route_seen and not metric_record_route_seen:
        errors.append(
            "shared collector Claude metric routing must include context: metric or context: datapoint; "
            "resource-only routes can send claude_code.* metrics to the default pipeline"
        )
    if token_route_seen and not exact_token_route_seen:
        errors.append(
            "shared collector Claude token routing must match claude_code.token.usage "
            "in context: metric or context: datapoint before metrics/claude_code_token_genai"
        )
    if log_route_seen and not log_record_route_seen:
        errors.append(
            "shared collector Claude log routing must include context: log; "
            "resource-only routes can send Claude Code log events to the default pipeline"
        )
    return errors


def _validate_claude_genai_pipeline(overlay: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    processors = overlay.get("processors") or {}
    if not isinstance(processors, dict):
        processors = {}
    transform = processors.get("transform/claude_code_genai")
    if transform is not None:
        transform_text = json.dumps(transform, sort_keys=True)
        for required in (
            "gen_ai.operation.name",
            "SPAN_KIND_CLIENT",
            "gen_ai.usage.input_tokens",
            "gen_ai.usage.output_tokens",
            "gen_ai.response.model",
            "gen_ai.provider.name",
            "gen_ai.agent.name",
            "invoke_workflow",
            "gen_ai.workflow.name",
        ):
            if required not in transform_text:
                errors.append(f"transform/claude_code_genai missing required GenAI mapping: {required}")

    galileo_transform = processors.get("transform/claude_code_galileo")
    if galileo_transform is not None:
        galileo_transform_text = json.dumps(galileo_transform, sort_keys=True)
        for required in (
            "user_prompt",
            "new_context",
            "response.model_output",
            "input.value",
            "output.value",
            "llm.input_messages.0.message.content",
            "llm.output_messages.0.message.content",
            "llm.tools",
            "gen_ai.tool.definitions",
            "claude_tools",
            "flatten",
            "delete_matching_keys",
            "replace_all_patterns",
            "merge_maps",
            "claude_code.galileo.available_tools_count",
            "execute_tool",
            "gen_ai.tool.name",
            "gen_ai.tool.call.arguments",
            "gen_ai.tool.call.result",
            "tool.output",
            "openinference.span.kind",
            GALILEO_OUTPUT_SCRATCH_ATTRIBUTE,
            "delete_key",
        ):
            if required not in galileo_transform_text:
                errors.append(
                    "transform/claude_code_galileo missing required content/tool mapping: "
                    + required
                )

    pipelines = ((overlay.get("service") or {}).get("pipelines")) or {}
    if not isinstance(pipelines, dict):
        return errors
    trace_pipe = pipelines.get("traces/claude_code")
    if transform is not None and not isinstance(trace_pipe, dict):
        errors.append(
            "collector defines transform/claude_code_genai but no reachable traces/claude_code pipeline"
        )
    if isinstance(trace_pipe, dict):
        pipe_processors = _pipeline_refs(trace_pipe.get("processors"))
        if "transform/claude_code_genai" not in pipe_processors:
            errors.append("traces/claude_code pipeline must run transform/claude_code_genai")
        else:
            batch_indexes = [
                index for index, component in enumerate(pipe_processors) if _is_batch_component(component)
            ]
            if batch_indexes and pipe_processors.index("transform/claude_code_genai") > min(batch_indexes):
                errors.append("traces/claude_code pipeline must run transform/claude_code_genai before batch")

    galileo_pipes = [
        pipe
        for pipe in pipelines.values()
        if isinstance(pipe, dict) and "otlp_http/galileo" in _pipeline_refs(pipe.get("exporters"))
    ]
    for galileo_pipe in galileo_pipes:
        pipe_processors = _pipeline_refs(galileo_pipe.get("processors"))
        for required in (
            "transform/claude_code_genai",
            "transform/claude_code_galileo",
            "filter/claude_code_galileo_genai",
        ):
            if required not in pipe_processors:
                errors.append(f"Galileo trace pipeline must run {required}")
        ordered = (
            "transform/claude_code_genai",
            "transform/claude_code_galileo",
            "filter/claude_code_galileo_genai",
        )
        if all(component in pipe_processors for component in ordered):
            indexes = [pipe_processors.index(component) for component in ordered]
            if indexes != sorted(indexes):
                errors.append(
                    "Galileo trace pipeline must normalize GenAI, map Galileo content, "
                    "then filter spans in that order"
                )

    galileo_filter = processors.get("filter/claude_code_galileo_genai")
    if galileo_filter is not None:
        filter_text = json.dumps(galileo_filter, sort_keys=True)
        for child_type in ("tool.execution", "tool.blocked_on_user", "hook"):
            if child_type not in filter_text:
                errors.append(
                    "filter/claude_code_galileo_genai must remove duplicate/non-logical child span: "
                    + child_type
                )

    token_transform = processors.get("transform/claude_code_token_metric_genai")
    if token_transform is not None:
        token_transform_text = json.dumps(token_transform, sort_keys=True)
        for required in (
            "gen_ai.client.token.usage",
            "gen_ai.token.type",
            "gen_ai.request.model",
            "gen_ai.response.model",
            "gen_ai.operation.name",
            "gen_ai.agent.name",
            "gen_ai.provider.name",
        ):
            if required not in token_transform_text:
                errors.append(
                    "transform/claude_code_token_metric_genai missing required GenAI token mapping: "
                    + required
                )
    exporters = overlay.get("exporters") or {}
    if not isinstance(exporters, dict):
        exporters = {}
    metrics_exporter = exporters.get("otlp_http/claude_code_metrics")
    if metrics_exporter is not None:
        metrics_endpoint = ""
        if isinstance(metrics_exporter, dict):
            metrics_endpoint = str(metrics_exporter.get("metrics_endpoint") or "")
        if not metrics_endpoint.endswith("/v2/datapoint/otlp"):
            errors.append("otlp_http/claude_code_metrics must send to Splunk OTLP metric ingest /v2/datapoint/otlp")
    splunk_metric_exporters = _splunk_metric_exporters(overlay)

    token_pipe = pipelines.get("metrics/claude_code_token_genai")
    token_histogram_pipe = pipelines.get("metrics/claude_code_token_histogram")
    connectors = overlay.get("connectors") or {}
    if not isinstance(connectors, dict):
        connectors = {}
    sum_connectors = sorted(
        str(name) for name in connectors if str(name).startswith("sum/claude_code_")
    )
    if sum_connectors:
        errors.append(
            "Claude token usage must not be exported by a sum connector; "
            "Splunk AI Agent Monitoring requires gen_ai.client.token.usage as a histogram: "
            + ", ".join(sum_connectors)
        )
    token_connector = connectors.get(GENAI_TOKEN_HISTOGRAM_CONNECTOR)
    if token_transform is not None and token_connector is None:
        errors.append(
            "metrics/claude_code_token_genai pipeline must define "
            + GENAI_TOKEN_HISTOGRAM_CONNECTOR
        )
    if token_connector is not None:
        if not isinstance(token_connector, dict):
            errors.append(GENAI_TOKEN_HISTOGRAM_CONNECTOR + " must be a mapping")
        else:
            datapoints = token_connector.get("datapoints") or []
            token_metric = next(
                (
                    item
                    for item in datapoints
                    if isinstance(item, dict)
                    and str(item.get("name") or "") == "gen_ai.client.token.usage"
                ),
                None,
            )
            if not isinstance(token_metric, dict):
                errors.append(
                    GENAI_TOKEN_HISTOGRAM_CONNECTOR
                    + " must define a gen_ai.client.token.usage datapoint metric"
                )
            else:
                if str(token_metric.get("unit") or "") != "{token}":
                    errors.append(
                        GENAI_TOKEN_HISTOGRAM_CONNECTOR + " must use unit {token}"
                    )
                conditions = [str(item) for item in token_metric.get("conditions") or []]
                if not any(
                    'metric.name == "gen_ai.client.token.usage"' in item
                    for item in conditions
                ):
                    errors.append(
                        GENAI_TOKEN_HISTOGRAM_CONNECTOR
                        + " must select metric.name gen_ai.client.token.usage"
                    )
                attribute_keys = {
                    str(item.get("key"))
                    for item in token_metric.get("attributes") or []
                    if isinstance(item, dict) and item.get("key") is not None
                }
                for required_attribute in (
                    "gen_ai.token.type",
                    "gen_ai.agent.name",
                    "gen_ai.operation.name",
                    "gen_ai.request.model",
                    "gen_ai.response.model",
                    "gen_ai.provider.name",
                ):
                    if required_attribute not in attribute_keys:
                        errors.append(
                            GENAI_TOKEN_HISTOGRAM_CONNECTOR
                            + " missing required attribute: "
                            + required_attribute
                        )
                histogram = token_metric.get("histogram")
                if not isinstance(histogram, dict):
                    errors.append(
                        GENAI_TOKEN_HISTOGRAM_CONNECTOR + " must emit a histogram"
                    )
                else:
                    buckets = tuple(histogram.get("buckets") or ())
                    if buckets != GENAI_TOKEN_HISTOGRAM_BUCKETS:
                        errors.append(
                            GENAI_TOKEN_HISTOGRAM_CONNECTOR
                            + " must use the OpenTelemetry GenAI token histogram buckets"
                        )
                    if str(histogram.get("count") or "") != "1":
                        errors.append(
                            GENAI_TOKEN_HISTOGRAM_CONNECTOR
                            + " histogram count expression must be 1"
                        )
                    if str(histogram.get("value") or "") != (
                        "Double(datapoint.value_int) + datapoint.value_double"
                    ):
                        errors.append(
                            GENAI_TOKEN_HISTOGRAM_CONNECTOR
                            + " histogram value must observe the numeric datapoint value"
                        )

        c2d = processors.get("cumulativetodelta/claude_code_tokens")
        include = c2d.get("include") if isinstance(c2d, dict) else None
        included_metrics = include.get("metrics") if isinstance(include, dict) else None
        if not isinstance(included_metrics, list) or "gen_ai.client.token.usage" not in included_metrics:
            errors.append(
                "cumulativetodelta/claude_code_tokens must include gen_ai.client.token.usage"
            )
    spanmetrics = connectors.get("span_metrics/claude_code_genai")
    if spanmetrics is not None:
        if isinstance(trace_pipe, dict) and "span_metrics/claude_code_genai" not in _pipeline_refs(trace_pipe.get("exporters")):
            errors.append("traces/claude_code pipeline must export to span_metrics/claude_code_genai")
        if isinstance(spanmetrics, dict) and str(spanmetrics.get("namespace") or "") != "gen_ai.client.operation":
            errors.append("span_metrics/claude_code_genai must use namespace gen_ai.client.operation")
        histogram = spanmetrics.get("histogram") if isinstance(spanmetrics, dict) else None
        if not isinstance(histogram, dict) or str(histogram.get("unit") or "") != "s":
            errors.append("span_metrics/claude_code_genai histogram must use unit s")
    duration_pipe = pipelines.get("metrics/claude_code_genai_duration")
    if spanmetrics is not None and not isinstance(duration_pipe, dict):
        errors.append("collector overlay defines span_metrics/claude_code_genai but no metrics/claude_code_genai_duration pipeline")
    if isinstance(duration_pipe, dict):
        if "span_metrics/claude_code_genai" not in _pipeline_refs(duration_pipe.get("receivers")):
            errors.append("metrics/claude_code_genai_duration pipeline must receive from span_metrics/claude_code_genai")
        if not set(_pipeline_refs(duration_pipe.get("exporters"))) & splunk_metric_exporters:
            errors.append(
                "metrics/claude_code_genai_duration pipeline must export to an OTLP metrics exporter ending in /v2/datapoint/otlp"
            )

    if token_transform is not None and not isinstance(token_pipe, dict):
        errors.append("collector overlay defines transform/claude_code_token_metric_genai but no metrics/claude_code_token_genai pipeline")
    if isinstance(token_pipe, dict):
        pipe_processors = _pipeline_refs(token_pipe.get("processors"))
        if not any(component.startswith("resource/claude_code") for component in pipe_processors):
            errors.append(
                "metrics/claude_code_token_genai pipeline must run a resource/claude_code processor"
            )
        if not _has_exact_token_route(overlay) and "filter/claude_code_token_metrics" not in pipe_processors:
            errors.append(
                "metrics/claude_code_token_genai pipeline must filter claude_code.token.usage "
                "unless an exact metric/datapoint routing entry already selects it"
            )
        for required_processor in (
            "transform/claude_code_token_metric_genai",
            "cumulativetodelta/claude_code_tokens",
        ):
            if required_processor not in pipe_processors:
                errors.append(f"metrics/claude_code_token_genai pipeline must run {required_processor}")
        if not any(_is_batch_component(component) for component in pipe_processors):
            errors.append("metrics/claude_code_token_genai pipeline must run a batch processor")
        ordered = (
            "transform/claude_code_token_metric_genai",
            "cumulativetodelta/claude_code_tokens",
        )
        if all(component in pipe_processors for component in ordered):
            indexes = [pipe_processors.index(component) for component in ordered]
            batch_indexes = [
                index for index, component in enumerate(pipe_processors) if _is_batch_component(component)
            ]
            if indexes != sorted(indexes) or (batch_indexes and indexes[-1] > min(batch_indexes)):
                errors.append(
                    "metrics/claude_code_token_genai pipeline must run transform, "
                    "cumulativetodelta, then batch in that order"
                )
        token_exporters = _pipeline_refs(token_pipe.get("exporters"))
        if GENAI_TOKEN_HISTOGRAM_CONNECTOR not in token_exporters:
            errors.append(
                "metrics/claude_code_token_genai pipeline must export to "
                + GENAI_TOKEN_HISTOGRAM_CONNECTOR
            )
        if "otlp_http/claude_code_metrics" in token_exporters:
            errors.append(
                "metrics/claude_code_token_genai must not export the counter directly; "
                "route it through " + GENAI_TOKEN_HISTOGRAM_CONNECTOR
            )
    if token_connector is not None and not isinstance(token_histogram_pipe, dict):
        errors.append(
            "collector overlay defines "
            + GENAI_TOKEN_HISTOGRAM_CONNECTOR
            + " but no metrics/claude_code_token_histogram pipeline"
        )
    if isinstance(token_histogram_pipe, dict):
        if GENAI_TOKEN_HISTOGRAM_CONNECTOR not in _pipeline_refs(
            token_histogram_pipe.get("receivers")
        ):
            errors.append(
                "metrics/claude_code_token_histogram pipeline must receive from "
                + GENAI_TOKEN_HISTOGRAM_CONNECTOR
            )
        if not set(_pipeline_refs(token_histogram_pipe.get("exporters"))) & splunk_metric_exporters:
            errors.append(
                "metrics/claude_code_token_histogram pipeline must export to an OTLP metrics exporter ending in /v2/datapoint/otlp"
            )
    return errors


def _validate_collector_overlay_structure(text: str) -> list[str]:
    """Structurally validate the rendered collector overlay: every component named in
    a pipeline must be defined, and the Galileo exporter (when present) must be wired
    into the traces pipeline. Uses PyYAML when available, else a regex fallback so the
    check still runs under the system python3 used by the setup.sh shim."""
    try:
        import yaml  # type: ignore
    except ImportError:
        yq = shutil.which("yq")
        if not yq:
            return _validate_overlay_structure_regex(text)
        parsed = subprocess.run(
            [yq, "-o=json", "."],
            input=text,
            capture_output=True,
            text=True,
            check=False,
        )
        if parsed.returncode != 0:
            return [f"collector overlay is not valid YAML: {parsed.stderr.strip()}"]
        try:
            overlay = json.loads(parsed.stdout)
        except json.JSONDecodeError as exc:
            return [f"collector overlay yq output is not valid JSON: {exc}"]
    else:
        try:
            overlay = yaml.safe_load(text)
        except yaml.YAMLError as exc:  # type: ignore[attr-defined]
            return [f"collector overlay is not valid YAML: {exc}"]
    if not isinstance(overlay, dict):
        return ["collector overlay is not a YAML mapping"]

    errors: list[str] = []
    defined = {
        kind: set((overlay.get(kind) or {}).keys()) if isinstance(overlay.get(kind), dict) else set()
        for kind in ("receivers", "processors", "exporters", "connectors")
    }
    pipelines = ((overlay.get("service") or {}).get("pipelines")) or {}
    if not isinstance(pipelines, dict) or not pipelines:
        return ["collector overlay has no service.pipelines"]

    galileo_defined = "otlp_http/galileo" in defined["exporters"]
    galileo_in_traces = False
    galileo_filter_seen = False
    galileo_transform_seen = False
    for pipe_name, pipe in pipelines.items():
        if not isinstance(pipe, dict):
            errors.append(f"collector overlay pipeline {pipe_name} is not a mapping")
            continue
        for kind in ("receivers", "processors", "exporters"):
            for component in pipe.get(kind) or []:
                component_defined = component in defined[kind]
                if kind in {"receivers", "exporters"} and component in defined["connectors"]:
                    component_defined = True
                if not component_defined:
                    errors.append(
                        f"collector overlay pipeline {pipe_name} references undefined "
                        f"{kind[:-1]} {component}"
                    )
        if pipe_name.startswith("traces") and "otlp_http/galileo" in (pipe.get("exporters") or []):
            galileo_in_traces = True
            processors = _pipeline_refs(pipe.get("processors"))
            if "transform/claude_code_galileo" in processors:
                galileo_transform_seen = True
            else:
                errors.append("Galileo trace pipeline must run transform/claude_code_galileo")
            if "filter/claude_code_galileo_genai" in processors:
                galileo_filter_seen = True
            else:
                errors.append("Galileo trace pipeline must run filter/claude_code_galileo_genai")
            ordered = (
                "transform/claude_code_genai",
                "transform/claude_code_galileo",
                "filter/claude_code_galileo_genai",
            )
            if all(component in processors for component in ordered):
                indexes = [processors.index(component) for component in ordered]
                if indexes != sorted(indexes):
                    errors.append(
                        "Galileo trace pipeline must normalize GenAI, map Galileo content, "
                        "then filter spans in that order"
                    )

    if galileo_defined and not galileo_in_traces:
        errors.append(
            "collector overlay defines otlp_http/galileo but no traces pipeline exports to it"
        )
    if galileo_defined and galileo_in_traces and not galileo_filter_seen:
        errors.append("collector overlay Galileo fan-out must filter non-GenAI spans before export")
    if galileo_defined and galileo_in_traces and not galileo_transform_seen:
        errors.append("collector overlay Galileo fan-out must map Claude content before export")
    errors.extend(_validate_claude_shared_routing(overlay))
    errors.extend(_validate_claude_genai_pipeline(overlay))
    return errors


def _validate_shared_routing_reference(text: str) -> list[str]:
    errors: list[str] = []
    required_fragments = {
        "context: span": "shared routing reference must route Claude traces in context: span",
        "context: metric": "shared routing reference must route Claude metrics in context: metric",
        "context: datapoint": "shared routing reference must route Claude metric datapoints in context: datapoint",
        "context: log": "shared routing reference must route Claude logs in context: log",
        'name == "claude_code.token.usage"': "shared routing reference must select claude_code.token.usage by metric name",
        "pipelines: [metrics/claude_code, metrics/claude_code_token_genai]": "shared token route must reach both native and GenAI token pipelines",
        "processors: [resource/claude_code, transform/claude_code_genai, batch]": "shared Claude trace pipeline must make transform/claude_code_genai reachable before batch",
        "exporters: [otlp_http/claude_code_traces, span_metrics/claude_code_genai]": "shared Claude trace pipeline must reach the duration connector",
        "exporters: [signal_to_metrics/claude_code_token_histogram]": "shared Claude token pipeline must reach the token histogram connector",
        "receivers: [signal_to_metrics/claude_code_token_histogram]": "shared token histogram output pipeline must receive from the connector",
        "metrics/claude_code_token_histogram": "shared routing reference must define the token histogram output pipeline",
    }
    for fragment, message in required_fragments.items():
        if fragment not in text:
            errors.append(message)
    return errors


def validate_output(
    output_dir: Path,
    json_output: bool = False,
    emit_output: bool = True,
    collector_config: Path | None = None,
) -> dict[str, Any]:
    required = [
        "metadata.json",
        "apply-plan.json",
        "coverage-report.json",
        "coverage-report.md",
        "doctor-report.md",
        "handoff.md",
        "runtime/galileo-handoff.md",
        "runtime/shared-collector-routing.md",
        "runtime/claude-code-o11y.env",
    ]
    errors: list[str] = []
    warnings: list[str] = []
    for rel in required:
        path = output_dir / rel
        if not path.exists():
            errors.append(f"missing rendered artifact: {rel}")
        elif path.is_file() and path.stat().st_size == 0:
            errors.append(f"empty rendered artifact: {rel}")

    settings_dir = output_dir / "settings"
    settings_files = sorted(settings_dir.glob("claude-settings.*.json")) if settings_dir.exists() else []
    if not settings_files:
        errors.append("no settings JSON files rendered")
    for settings_file in settings_files:
        try:
            doc = json.loads(settings_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{settings_file.name}: invalid JSON: {exc}")
            continue
        env = doc.get("env")
        if not isinstance(env, dict):
            errors.append(f"{settings_file.name}: missing env block")
            continue
        if env.get("CLAUDE_CODE_ENABLE_TELEMETRY") != "1":
            errors.append(f"{settings_file.name}: CLAUDE_CODE_ENABLE_TELEMETRY must be '1'")
        if env.get("OTEL_TRACES_EXPORTER") == "otlp" and env.get("CLAUDE_CODE_ENHANCED_TELEMETRY_BETA") != "1":
            errors.append(
                f"{settings_file.name}: traces exporter requires CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1"
            )
        # Detailed beta tracing requires both the flag and its separate endpoint.
        if env.get("ENABLE_BETA_TRACING_DETAILED") == "1" and not env.get("BETA_TRACING_ENDPOINT"):
            errors.append(
                f"{settings_file.name}: ENABLE_BETA_TRACING_DETAILED=1 requires BETA_TRACING_ENDPOINT"
            )
        if "splunk-direct" in settings_file.name:
            if "OTEL_EXPORTER_OTLP_HEADERS" in env:
                errors.append(
                    f"{settings_file.name}: splunk-direct must not embed OTEL_EXPORTER_OTLP_HEADERS; use otelHeadersHelper"
                )
            if not doc.get("otelHeadersHelper"):
                errors.append(f"{settings_file.name}: splunk-direct requires otelHeadersHelper")
            rendered_helper = output_dir / "bin" / "claude-code-otel-headers.sh"
            if not rendered_helper.exists():
                errors.append(
                    f"{settings_file.name}: splunk-direct requires rendered headers helper "
                    "bin/claude-code-otel-headers.sh"
                )
            elif not os.access(rendered_helper, os.X_OK):
                errors.append(
                    f"{settings_file.name}: rendered headers helper bin/claude-code-otel-headers.sh "
                    "must be executable"
                )
        elif doc.get("otelHeadersHelper"):
            rendered_helper = output_dir / "bin" / "claude-code-otel-headers.sh"
            if not rendered_helper.exists():
                errors.append(
                    f"{settings_file.name}: otelHeadersHelper requires rendered helper "
                    "bin/claude-code-otel-headers.sh"
                )
            elif not os.access(rendered_helper, os.X_OK):
                errors.append(
                    f"{settings_file.name}: rendered headers helper bin/claude-code-otel-headers.sh "
                    "must be executable"
                )
        if "external-collector" in settings_file.name:
            static_headers = str(env.get("OTEL_EXPORTER_OTLP_HEADERS") or "")
            if re.search(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}", static_headers):
                errors.append(
                    f"{settings_file.name}: external header placeholders must be resolved by otelHeadersHelper, not emitted literally"
                )

    env_dir = output_dir / "env"
    if env_dir.exists():
        for env_file in sorted(env_dir.glob("*.env")):
            text = env_file.read_text(encoding="utf-8")
            if "CLAUDE_CODE_ENABLE_TELEMETRY=1" not in text:
                errors.append(f"{env_file.name}: missing CLAUDE_CODE_ENABLE_TELEMETRY=1 export")

    collector_yaml = output_dir / "collector" / "claude-code-o11y-local-collector.yaml"
    if collector_yaml.exists():
        text = collector_yaml.read_text(encoding="utf-8")
        if "send_otlp_histograms: true" not in text:
            errors.append("collector overlay must set send_otlp_histograms: true")
        if "otlp_http/galileo" in text and 'Galileo-API-Key: "${env:GALILEO_API_KEY}"' not in text:
            errors.append("collector overlay Galileo exporter must reference ${env:GALILEO_API_KEY}")
        if "otlp_http/claude_code_traces" not in text:
            errors.append("collector overlay missing claude_code_traces exporter")
        # CC-09: structural validation. Parse the overlay and confirm every component
        # referenced in a pipeline is defined, and that the Galileo exporter (when
        # present) is wired into the traces pipeline. Degrades to the substring checks
        # above if PyYAML is unavailable.
        errors.extend(_validate_collector_overlay_structure(text))

    shared_routing = output_dir / "runtime" / "shared-collector-routing.md"
    if shared_routing.exists():
        errors.extend(_validate_shared_routing_reference(shared_routing.read_text(encoding="utf-8")))

    if collector_config is not None:
        if not collector_config.is_file():
            errors.append(f"collector config does not exist: {collector_config}")
        else:
            external_errors = _validate_collector_overlay_structure(
                collector_config.read_text(encoding="utf-8")
            )
            errors.extend(
                f"collector config {collector_config}: {error}" for error in external_errors
            )

    headers_helper = output_dir / "bin" / "claude-code-otel-headers.sh"
    if headers_helper.exists():
        text = headers_helper.read_text(encoding="utf-8")
        if "set -euo pipefail" not in text:
            errors.append("otel headers helper must set -euo pipefail")
        if "SPLUNK_O11Y_TOKEN_FILE" not in text and "header_env =" not in text:
            errors.append(
                "otel headers helper must read SPLUNK_O11Y_TOKEN_FILE or resolve external header environment variables"
            )

    if (output_dir / "apply-plan.json").exists():
        plan = json.loads((output_dir / "apply-plan.json").read_text(encoding="utf-8"))
        joined = json.dumps(plan)
        for forbidden in (" --token ", " --access-token ", " --sf-token ", " --o11y-token ", " --api-key ", " --password "):
            if forbidden in f" {joined} ":
                errors.append(f"apply-plan.json contains forbidden direct-secret flag: {forbidden.strip()}")
        settings_steps = [step for step in plan.get("steps", []) if step.get("section") == "settings"]
        if not settings_steps:
            errors.append("apply-plan.json missing settings section")
        else:
            for step in settings_steps:
                for command in step.get("commands", []):
                    if not command or command[0] != "merge-settings":
                        errors.append("apply-plan.json settings section must use merge-settings, not overwrite")

    errors.extend(scan_rendered_for_secret_leaks(output_dir))
    metadata = {}
    if (output_dir / "metadata.json").exists():
        try:
            metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
            # CC-08: import metadata errors that are not already present (the live
            # leak rescan above already covers metadata's leak lines), so a rendered
            # leak is not double-counted.
            for err in metadata.get("errors", []):
                if err not in errors:
                    errors.append(err)
            warnings.extend(metadata.get("warnings", []))
        except json.JSONDecodeError as exc:
            errors.append(f"metadata.json invalid JSON: {exc}")
    payload = {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "output_dir": str(output_dir),
        "collector_config": str(collector_config) if collector_config is not None else "",
    }
    if emit_output:
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


def is_skill_headers_helper(value: object) -> bool:
    try:
        path = Path(str(value)).expanduser()
    except (TypeError, ValueError):
        return False
    return path.name == "claude-code-otel-headers.sh" and path.parent.name == "bin"


def merge_settings_file(source: Path, target: Path) -> None:
    source_doc = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(source_doc, dict):
        raise UsageError(f"rendered settings file is not a JSON object: {source}")
    source_env = source_doc.get("env") or {}
    if not isinstance(source_env, dict):
        raise UsageError(f"rendered settings 'env' block is not an object: {source}")

    if target.exists():
        try:
            target_doc = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise UsageError(f"existing settings file is not valid JSON: {target}: {exc}") from exc
        if not isinstance(target_doc, dict):
            raise UsageError(f"existing settings root is not a JSON object: {target}")
    else:
        target_doc = {}

    existing_env = target_doc.get("env")
    if existing_env is None:
        existing_env = {}
    elif not isinstance(existing_env, dict):
        raise UsageError(f"existing settings env is not a JSON object: {target}")

    merged_env: dict[str, Any] = {}
    for key, value in existing_env.items():
        if is_managed_env_key(str(key)):
            # Drop all previously-managed keys so stale values (e.g. a
            # BETA_TRACING_ENDPOINT from a prior destination) do not linger.
            continue
        merged_env[key] = value
    for key, value in source_env.items():
        merged_env[str(key)] = value
    target_doc["env"] = merged_env

    # Managed top-level keys are authoritative when the source sets them. When
    # switching away from direct/dynamic-header mode, remove only the helper path
    # generated by this skill; preserve an unrelated operator-owned helper.
    for key in MANAGED_TOP_LEVEL_KEYS:
        if key in source_doc:
            target_doc[key] = source_doc[key]
        elif (
            target_doc.get("_managedBy") == MANAGED_SETTINGS_MARKER
            and key == "otelHeadersHelper"
            and is_skill_headers_helper(target_doc.get(key))
        ):
            target_doc.pop(key, None)
    target_doc["_managedBy"] = MANAGED_SETTINGS_MARKER

    target.parent.mkdir(parents=True, exist_ok=True)
    prior_mode: int | None = None
    if target.exists():
        prior_mode = target.stat().st_mode
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        backup = target.with_name(f"{target.name}.bak.{timestamp}")
        shutil.copy2(target, backup)

    temp_target = target.with_name(f".{target.name}.tmp.{os.getpid()}")
    try:
        write_json(temp_target, target_doc)
        if prior_mode is not None:
            temp_target.chmod(prior_mode)
        os.replace(temp_target, target)
    finally:
        if temp_target.exists():
            temp_target.unlink()


def apply_sections(
    config: dict[str, Any],
    output_dir: Path,
    sections: list[str],
    dry_run: bool,
    json_output: bool,
) -> dict[str, Any]:
    plan_path = output_dir / "apply-plan.json"
    metadata_path = output_dir / "metadata.json"
    if plan_path.exists():
        validate_output(output_dir, json_output=False, emit_output=not json_output)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    else:
        metadata = render(config, output_dir, json_output=False)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    selected = list(APPLY_SECTIONS) if sections == ["all"] else sections
    unknown = sorted(set(selected) - set(APPLY_SECTIONS))
    if unknown:
        raise UsageError(f"unknown apply section(s): {', '.join(unknown)}")
    if plan.get("destination") == "all" and "settings" in selected:
        raise UsageError(
            "destination=all renders multiple settings profiles; apply one concrete destination profile at a time"
        )
    if (
        not dry_run
        and "settings" in selected
        and bool_config(config["claude_code"].get("log_assistant_responses"))
    ):
        require_assistant_response_capable_claude()
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
            if command[0] == "render-only":
                continue
            if command[0] == "install":
                source = Path(command[-2])
                target = Path(os.path.expandvars(os.path.expanduser(command[-1])))
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.resolve() != target.resolve():
                    shutil.copy2(source, target)
                if len(command) >= 3 and command[2] == "0755":
                    target.chmod(target.stat().st_mode | 0o111)
            elif command[0] == "install-executable":
                source = Path(command[-2])
                target = Path(os.path.expandvars(os.path.expanduser(command[-1])))
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.resolve() != target.resolve():
                    shutil.copy2(source, target)
                target.chmod(target.stat().st_mode | 0o111)
            elif command[0] == "merge-settings":
                merge_settings_file(
                    Path(command[1]),
                    Path(os.path.expandvars(os.path.expanduser(command[2]))),
                )
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
        "agents": ["claude-code"],
        "destinations": sorted(VALID_DESTINATIONS),
        "settings_scopes": sorted(VALID_SCOPES),
        "protocols": sorted(VALID_PROTOCOLS),
        "accepted_protocol_aliases": PROTOCOL_ALIASES,
        "apply_sections": list(APPLY_SECTIONS) + ["all"],
        "sources": [
            "https://code.claude.com/docs/en/monitoring-usage",
            "https://dev.splunk.com/observability/reference/api/ingest_data/latest",
            "https://docs.galileo.ai/how-to-guides/third-party-integrations/otel",
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
    parser.add_argument("--environment", default="")
    parser.add_argument("--service-name", default="")
    parser.add_argument("--realm", default="")
    parser.add_argument("--destination", choices=sorted(VALID_DESTINATIONS), default="")
    parser.add_argument("--settings-scope", choices=sorted(VALID_SCOPES), default="")
    parser.add_argument("--local-collector-endpoint", default="")
    parser.add_argument("--collector-receiver-endpoint", default="")
    parser.add_argument("--collector-config", default="")
    parser.add_argument("--galileo-project", default="")
    parser.add_argument("--galileo-log-stream", default="")
    parser.add_argument("--galileo-otel-endpoint", default="")
    parser.add_argument("--galileo-console-url", default="")
    parser.add_argument("--galileo-enabled", action="store_true")
    parser.add_argument("--provider-name", default="")
    parser.add_argument("--model-alias", action="append", default=[])
    parser.add_argument("--enable-traces-beta", action="store_true")
    parser.add_argument("--disable-traces-beta", action="store_true")
    parser.add_argument("--enable-detailed-traces", action="store_true")
    parser.add_argument("--disable-detailed-traces", action="store_true")
    parser.add_argument("--disable-galileo", action="store_true")
    parser.add_argument("--accept-content-capture", action="store_true")
    parser.add_argument("--log-user-prompts", action="store_true")
    parser.add_argument("--log-assistant-responses", action="store_true")
    parser.add_argument("--log-tool-details", action="store_true")
    parser.add_argument("--log-tool-content", action="store_true")
    parser.add_argument("--log-raw-api-bodies", nargs="?", const="1", default=None)
    parser.add_argument("--metric-export-interval-ms", type=int)
    parser.add_argument("--logs-export-interval-ms", type=int)
    parser.add_argument("--traces-export-interval-ms", type=int)
    parser.add_argument("--external-collector-endpoint", default="")
    parser.add_argument("--external-collector-protocol", choices=sorted(VALID_PROTOCOL_INPUTS), default="")
    parser.add_argument("--external-trace-endpoint", default="")
    parser.add_argument("--external-metric-endpoint", default="")
    parser.add_argument("--external-log-endpoint", default="")
    parser.add_argument("--external-header", action="append", default=[])
    parser.add_argument("--external-ca-certificate", default="")
    parser.add_argument("--external-client-certificate", default="")
    parser.add_argument("--external-client-private-key", default="")
    parser.add_argument("--resource-attribute", action="append", default=[])
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
            collector_config = (
                Path(args.collector_config).expanduser().resolve()
                if args.collector_config
                else None
            )
            validate_output(
                output_dir,
                args.json,
                collector_config=collector_config,
            )
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
            print(f"rendered Claude Code O11y assets -> {output_dir}")
        return 0
    except SystemExit:
        raise
    except Exception as exc:
        return command_failed(exc, json_output)


if __name__ == "__main__":
    raise SystemExit(main())
