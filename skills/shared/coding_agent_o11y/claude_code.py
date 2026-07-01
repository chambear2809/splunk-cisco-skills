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
    write_json,
    write_text,
)


SKILL_NAME = "splunk-observability-claude-code-instrumentation-setup"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "splunk-observability-claude-code-instrumentation-rendered"
VALID_DESTINATIONS = {"local-collector", "external-collector", "splunk-direct", "all"}
VALID_SCOPES = {"user", "project", "managed"}
VALID_PROTOCOLS = {"grpc", "http/json", "http/protobuf"}
PROTOCOL_ALIASES = {"otlp-http": "http/protobuf", "otlp-grpc": "grpc"}
VALID_PROTOCOL_INPUTS = VALID_PROTOCOLS | set(PROTOCOL_ALIASES)
APPLY_SECTIONS = ("settings", "env-helper", "collector-overlay", "galileo-handoff")
MANAGED_SETTINGS_MARKER = "splunk-observability-claude-code-instrumentation-setup"

MANAGED_ENV_PREFIXES = ("CLAUDE_CODE_", "OTEL_")
# Managed env keys that do not share the CLAUDE_CODE_/OTEL_ prefixes but are still
# owned by this skill (detailed beta tracing). Tracked explicitly so merge_settings_file
# strips stale values when the operator switches destinations or disables detailed traces.
MANAGED_ENV_EXACT = ("ENABLE_BETA_TRACING_DETAILED", "BETA_TRACING_ENDPOINT")
MANAGED_TOP_LEVEL_KEYS = ("otelHeadersHelper",)


def is_managed_env_key(key: str) -> bool:
    return key in MANAGED_ENV_EXACT or any(key.startswith(prefix) for prefix in MANAGED_ENV_PREFIXES)


DEFAULT_SPEC: dict[str, Any] = {
    "api_version": "splunk-observability-claude-code-instrumentation-setup/v1",
    "claude_code": {
        "settings_scope": "user",
        "environment": "prod",
        "service_name": "claude-code",
        "realm": "us0",
        "destination": "local-collector",
        "enable_traces_beta": True,
        # Detailed beta tracing emits the child spans (claude_code.llm_request,
        # claude_code.tool, ...) that Galileo Luna scorers require. Without it Claude
        # Code emits only the top-level claude_code.interaction workflow span and
        # span-scoped Luna scorers fail with "no child spans found". Requires
        # ENABLE_BETA_TRACING_DETAILED=1 plus a BETA_TRACING_ENDPOINT (a SEPARATE
        # endpoint from OTEL_EXPORTER_OTLP_TRACES_ENDPOINT per Claude Code docs).
        "enable_detailed_traces": True,
        "galileo_enabled": False,
        "galileo_console_url": "",
        "galileo_project": "",
        "galileo_log_stream": "default",
        "galileo_otel_endpoint": "https://api.galileo.ai/otel/traces",
        "local_collector_endpoint": "http://127.0.0.1:14318",
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
        "accept_content_capture": False,
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
    if not (parsed.path.endswith("/otel/traces") or parsed.path.endswith("/otel/v1/traces")):
        raise UsageError("galileo_otel_endpoint must end with /otel/traces or /otel/v1/traces")
    return parsed


def galileo_endpoint_from_console(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise UsageError("galileo console URL must be https:// with a host")
    if parsed.username or parsed.password:
        raise UsageError("galileo console URL must not include credentials")
    host = parsed.hostname
    # Only the well-known console./api. conventions can be derived deterministically.
    # A console host maps to the api host by swapping the leading label; an api host
    # is already correct. Anything else is ambiguous and must be passed explicitly via
    # --galileo-otel-endpoint rather than silently guessed (which previously produced
    # unreachable hosts like api.app.galileo.ai).
    if host.startswith("console."):
        host = "api." + host[len("console.") :]
    elif host.startswith("api."):
        pass
    else:
        raise UsageError(
            "galileo console URL host must start with 'console.' (for example "
            "https://console.<tenant>/) so the api. endpoint can be derived; "
            "otherwise pass the full endpoint with --galileo-otel-endpoint"
        )
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return f"https://{host}/otel/traces"


REALM_RE = re.compile(r"^[a-z0-9]+$")


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


def load_spec_with_args(args: argparse.Namespace) -> dict[str, Any]:
    config = copy.deepcopy(DEFAULT_SPEC)
    if args.spec:
        config = deep_merge(config, load_structured_file(Path(args.spec).expanduser()))
    cc = config.setdefault("claude_code", {})

    cli_updates = {
        "environment": args.environment,
        "service_name": args.service_name,
        "realm": args.realm,
        "destination": args.destination,
        "settings_scope": args.settings_scope,
        "local_collector_endpoint": args.local_collector_endpoint,
        "external_collector_endpoint": args.external_collector_endpoint,
        "galileo_project": args.galileo_project,
        "galileo_log_stream": args.galileo_log_stream,
        "galileo_otel_endpoint": args.galileo_otel_endpoint,
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
        cc["galileo_otel_endpoint"] = galileo_endpoint_from_console(args.galileo_console_url)

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
            ensure_safe_external_value(f"TLS {key}", value)
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
    return config


def validate_config(config: dict[str, Any]) -> tuple[list[str], list[str]]:
    cc = config["claude_code"]
    errors: list[str] = []
    warnings: list[str] = []

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
    if galileo_enabled and destination in {"local-collector", "external-collector", "all"}:
        if not str(cc.get("galileo_project") or "").strip():
            errors.append("Galileo integration requires --galileo-project when enabled")
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
                ensure_safe_external_value(label, str(value), reject_token_like=True)
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
    ]
    if any(bool_config(value) for _, value in content_flags) and not bool_config(cc.get("accept_content_capture")):
        errors.append(
            "prompt/response/tool content capture requires --accept-content-capture"
        )

    if bool_config(cc.get("log_tool_content")) and not bool_config(cc.get("enable_traces_beta")):
        warnings.append("OTEL_LOG_TOOL_CONTENT is set but traces beta is disabled; tool content is only attached to spans")

    for key, value in (cc.get("external_headers") or {}).items():
        try:
            ensure_safe_external_header(str(key), str(value))
        except UsageError as exc:
            errors.append(str(exc))
    for key, value in (cc.get("external_tls") or {}).items():
        try:
            ensure_safe_external_value(f"TLS {key}", str(value))
        except UsageError as exc:
            errors.append(str(exc))
    for key, value in (cc.get("resource_attributes") or {}).items():
        try:
            ensure_safe_external_value(f"resource attribute {key}", str(value))
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
    # point at wherever traces are sent so the child spans reach the same backend.
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
            header_pairs = [f"{k}={v}" for k, v in sorted(external_headers.items())]
            env["OTEL_EXPORTER_OTLP_HEADERS"] = ",".join(header_pairs)
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
    if bool_config(cc.get("log_tool_details")):
        env["OTEL_LOG_TOOL_DETAILS"] = "1"
    if bool_config(cc.get("log_tool_content")):
        env["OTEL_LOG_TOOL_CONTENT"] = "1"

    resource_attrs: dict[str, str] = {}
    resource_attrs["service.name"] = str(cc["service_name"])
    resource_attrs["deployment.environment"] = str(cc["environment"])
    for key, value in (cc.get("resource_attributes") or {}).items():
        resource_attrs[str(key)] = str(value)
    env["OTEL_RESOURCE_ATTRIBUTES"] = ",".join(
        f"{k}={v}" for k, v in sorted(resource_attrs.items())
    )
    env["OTEL_SERVICE_NAME"] = str(cc["service_name"])

    return env


def render_settings_file(config: dict[str, Any], destination: str, output_dir: Path) -> str:
    env_config = deep_merge({}, config)
    env_config["claude_code"] = dict(env_config["claude_code"])
    env_config["claude_code"]["destination"] = destination
    env = render_env_dict(env_config, output_dir)
    settings: dict[str, Any] = {"env": env}
    if destination == "splunk-direct":
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
    for key in sorted(env):
        lines.append(f"export {key}={shell_quote(env[key])}")
    lines.append("")
    return "\n".join(lines)


def render_collector_overlay(config: dict[str, Any]) -> str:
    cc = config["claude_code"]
    realm = str(cc.get("realm") or "us0")
    service_name = str(cc["service_name"])
    environment = str(cc["environment"])
    receiver_endpoint = local_collector_receiver_endpoint(cc["local_collector_endpoint"])
    galileo_enabled = bool_config(cc.get("galileo_enabled"))
    galileo_project = str(cc.get("galileo_project") or "")
    galileo_log_stream = str(cc.get("galileo_log_stream") or "default")
    galileo_endpoint_str = str(cc.get("galileo_otel_endpoint") or "https://api.galileo.ai/otel/traces")
    if galileo_enabled:
        parse_galileo_endpoint(galileo_endpoint_str)
    trace_exporters = ["otlphttp/claude_code_traces"]
    if galileo_enabled:
        trace_exporters.append("otlphttp/galileo")

    galileo_block = ""
    if galileo_enabled:
        galileo_block = f"""  otlphttp/galileo:
    endpoint: {yaml_quote(galileo_endpoint_str)}
    headers:
      Galileo-API-Key: "${{env:GALILEO_API_KEY}}"
      project: {yaml_quote(galileo_project)}
      logstream: {yaml_quote(galileo_log_stream)}
"""

    return f"""# Local collector overlay for Claude Code OTel.
# Merge into a Splunk Distribution of OpenTelemetry Collector gateway.
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
      - key: deployment.environment
        value: {yaml_quote(environment)}
        action: upsert

exporters:
  otlphttp/claude_code_traces:
    traces_endpoint: {yaml_quote(f"https://ingest.{realm}.observability.splunkcloud.com/v2/trace/otlp")}
    headers:
      X-SF-TOKEN: "${{env:SPLUNK_ACCESS_TOKEN}}"
  otlphttp/claude_code_logs:
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
      processors: [resource/claude_code, batch/claude_code]
      exporters: [{", ".join(trace_exporters)}]
    metrics/claude_code:
      receivers: [otlp/claude_code]
      processors: [resource/claude_code, batch/claude_code]
      exporters: [signalfx/claude_code]
    logs/claude_code:
      receivers: [otlp/claude_code]
      processors: [resource/claude_code, batch/claude_code]
      exporters: [otlphttp/claude_code_logs]
"""


def render_headers_helper() -> str:
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
    galileo_endpoint = str(cc.get("galileo_otel_endpoint") or "https://api.galileo.ai/otel/traces")
    galileo_console_url = str(cc.get("galileo_console_url") or "")
    destination = str(cc.get("destination"))
    api_base = re.sub(r"/otel(?:/v1)?/traces/?$", "", galileo_endpoint.rstrip("/"))
    platform_cmd = [
        "bash skills/galileo-platform-setup/scripts/setup.sh --render \\",
        f"  --project-name {shell_quote(galileo_project)} \\",
        f"  --log-stream {shell_quote(galileo_log_stream)} \\",
    ]
    if galileo_console_url:
        platform_cmd.append(f"  --galileo-console-url {shell_quote(galileo_console_url)}")
    else:
        platform_cmd.append(f"  --galileo-otel-endpoint {shell_quote(galileo_endpoint)}")
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
        "- Traces to Splunk Observability Cloud (`otlphttp/claude_code_traces`) and",
        "  optionally to Galileo (`otlphttp/galileo`).",
        "- Metrics to Splunk Observability Cloud via `signalfx/claude_code`.",
        "- Logs to Splunk Observability Cloud via `otlphttp/claude_code_logs`.",
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
    if destination in {"splunk-direct", "all"}:
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
                "ENABLE_BETA_TRACING_DETAILED=1 + BETA_TRACING_ENDPOINT emit the child spans "
                "(claude_code.llm_request, claude_code.tool) that Galileo Luna span scorers require; "
                "without them only the top-level claude_code.interaction span is produced."
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
            "summary": "Local collector overlay fans Claude Code OTel out to Splunk O11y and (optionally) Galileo traces; external collector mode is operator-owned.",
            "source_url": "https://help.splunk.com/en/splunk-observability-cloud/manage-data/splunk-distribution-of-the-opentelemetry-collector",
        },
        {
            "key": "splunk.histograms",
            "status": "render" if destination in {"local-collector", "all"} else "not_applicable",
            "summary": "Collector overlay sets send_otlp_histograms: true for Claude Code metrics.",
            "source_url": "https://help.splunk.com/en/splunk-observability-cloud/manage-data/metrics-metadata-and-events/metrics-events-and-metadata/get-histogram-data-in",
        },
        {
            "key": "galileo.traces",
            "status": "render" if galileo_enabled and destination != "splunk-direct" else "not_applicable",
            "summary": "Galileo Observe ingests Claude Code traces via otlphttp/galileo when the collector fan-out is enabled.",
            "source_url": "https://v2docs.galileo.ai/how-to-guides/logging-with-otel",
        },
        {
            "key": "galileo.genai_attributes",
            "status": "render" if galileo_enabled and destination != "splunk-direct" else "not_applicable",
            "summary": (
                "Galileo /otel/traces only ingests spans that carry OTel GenAI semantic-convention "
                "attributes (gen_ai.*). Claude Code detailed beta spans satisfy this; spans without "
                "gen_ai.* are rejected with partialSuccess 'No GenAI patterns detected in spans'. "
                "Enable detailed traces so llm_request spans (which carry gen_ai.*) are emitted."
            ),
            "source_url": "https://v2docs.galileo.ai/how-to-guides/logging-with-otel",
        },
        {
            "key": "galileo.non_public_tenant",
            "status": "render" if galileo_enabled and destination != "splunk-direct" else "not_applicable",
            "summary": (
                "For non-public Galileo tenants (e.g. Galileo Cloud, Splunk-hosted Agent Observability), "
                "pass --galileo-console-url; the console. host is rewritten to api. and the OTLP endpoint "
                "becomes https://api.<tenant>/otel/traces. The public api.galileo.ai default rejects "
                "other tenants' keys with HTTP 401."
            ),
            "source_url": "https://v2docs.galileo.ai/how-to-guides/logging-with-otel",
        },
        {
            "key": "content_capture",
            "status": "render" if bool_config(cc.get("accept_content_capture")) else "render_disabled",
            "summary": "OTEL_LOG_USER_PROMPTS / _RESPONSES / _TOOL_DETAILS / _TOOL_CONTENT are gated behind --accept-content-capture.",
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
            "- For local-collector, merge the overlay into your Splunk Distribution of OpenTelemetry Collector configuration.",
            "- For Galileo fan-out, provision the project and log stream via `galileo-platform-setup` and export `GALILEO_API_KEY`.",
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
                "Merge `collector/claude-code-o11y-local-collector.yaml` into a Splunk",
                "Distribution of OpenTelemetry Collector gateway to fan Claude Code",
                "traces to Splunk O11y (and Galileo when enabled).",
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
    if destination in {"splunk-direct", "all"}:
        write_text(
            output_dir / "bin" / "claude-code-otel-headers.sh",
            render_headers_helper(),
            executable=True,
        )

    write_text(output_dir / "runtime" / "galileo-handoff.md", render_galileo_handoff(config))
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
    Galileo exporter whenever otlphttp/galileo is defined, and that the core exporters
    are referenced. Used when PyYAML is not installed (the setup.sh shim runs the
    system python3, which may lack it)."""
    errors: list[str] = []
    galileo_defined = re.search(r"^\s*otlphttp/galileo:\s*$", text, re.MULTILINE) is not None
    # Extract each pipeline's exporters: line.
    traces_exporters = ""
    m = re.search(r"traces/claude_code:.*?exporters:\s*\[([^\]]*)\]", text, re.DOTALL)
    if m:
        traces_exporters = m.group(1)
    if galileo_defined and "otlphttp/galileo" not in traces_exporters:
        errors.append(
            "collector overlay defines otlphttp/galileo but no traces pipeline exports to it"
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
        return _validate_overlay_structure_regex(text)
    try:
        overlay = yaml.safe_load(text)
    except yaml.YAMLError as exc:  # type: ignore[attr-defined]
        return [f"collector overlay is not valid YAML: {exc}"]
    if not isinstance(overlay, dict):
        return ["collector overlay is not a YAML mapping"]

    errors: list[str] = []
    defined = {
        kind: set((overlay.get(kind) or {}).keys()) if isinstance(overlay.get(kind), dict) else set()
        for kind in ("receivers", "processors", "exporters")
    }
    pipelines = ((overlay.get("service") or {}).get("pipelines")) or {}
    if not isinstance(pipelines, dict) or not pipelines:
        return ["collector overlay has no service.pipelines"]

    galileo_defined = "otlphttp/galileo" in defined["exporters"]
    galileo_in_traces = False
    for pipe_name, pipe in pipelines.items():
        if not isinstance(pipe, dict):
            errors.append(f"collector overlay pipeline {pipe_name} is not a mapping")
            continue
        for kind in ("receivers", "processors", "exporters"):
            for component in pipe.get(kind) or []:
                if component not in defined[kind]:
                    errors.append(
                        f"collector overlay pipeline {pipe_name} references undefined "
                        f"{kind[:-1]} {component}"
                    )
        if pipe_name.startswith("traces") and "otlphttp/galileo" in (pipe.get("exporters") or []):
            galileo_in_traces = True

    if galileo_defined and not galileo_in_traces:
        errors.append(
            "collector overlay defines otlphttp/galileo but no traces pipeline exports to it"
        )
    return errors


def validate_output(output_dir: Path, json_output: bool = False) -> dict[str, Any]:
    required = [
        "metadata.json",
        "apply-plan.json",
        "coverage-report.json",
        "coverage-report.md",
        "doctor-report.md",
        "handoff.md",
        "runtime/galileo-handoff.md",
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
        # Detailed beta tracing requires BOTH the flag and a separate endpoint, or Claude
        # Code emits only the top-level span and Galileo Luna span scorers get no children.
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
        if "otlphttp/galileo" in text and 'Galileo-API-Key: "${env:GALILEO_API_KEY}"' not in text:
            errors.append("collector overlay Galileo exporter must reference ${env:GALILEO_API_KEY}")
        if "otlphttp/claude_code_traces" not in text:
            errors.append("collector overlay missing claude_code_traces exporter")
        # CC-09: structural validation. Parse the overlay and confirm every component
        # referenced in a pipeline is defined, and that the Galileo exporter (when
        # present) is wired into the traces pipeline. Degrades to the substring checks
        # above if PyYAML is unavailable.
        errors.extend(_validate_collector_overlay_structure(text))

    headers_helper = output_dir / "bin" / "claude-code-otel-headers.sh"
    if headers_helper.exists():
        text = headers_helper.read_text(encoding="utf-8")
        if "set -euo pipefail" not in text:
            errors.append("otel headers helper must set -euo pipefail")
        if "SPLUNK_O11Y_TOKEN_FILE" not in text:
            errors.append("otel headers helper must read SPLUNK_O11Y_TOKEN_FILE")

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

    # TC-03: managed top-level keys are authoritative. If the rendered source sets one,
    # adopt it; otherwise remove any stale value (e.g. an otelHeadersHelper left over
    # from a prior splunk-direct render when switching to a collector destination).
    # These keys are only ever written by this skill, so unconditional reconciliation
    # is safe and mirrors how the env loop already drops stale managed env keys.
    for key in MANAGED_TOP_LEVEL_KEYS:
        if key in source_doc:
            target_doc[key] = source_doc[key]
        else:
            target_doc.pop(key, None)
    target_doc["_managedBy"] = MANAGED_SETTINGS_MARKER

    target.parent.mkdir(parents=True, exist_ok=True)
    write_json(target, target_doc)


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
        validate_output(output_dir, json_output=False)
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
                target = Path(os.path.expandvars(os.path.expanduser(command[-1])))
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(command[-2], target)
                if len(command) >= 3 and command[2] == "0755":
                    target.chmod(target.stat().st_mode | 0o111)
            elif command[0] == "install-executable":
                target = Path(os.path.expandvars(os.path.expanduser(command[-1])))
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(command[-2], target)
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
            "https://v2docs.galileo.ai/how-to-guides/logging-with-otel",
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
    parser.add_argument("--galileo-project", default="")
    parser.add_argument("--galileo-log-stream", default="")
    parser.add_argument("--galileo-otel-endpoint", default="")
    parser.add_argument("--galileo-console-url", default="")
    parser.add_argument("--galileo-enabled", action="store_true")
    parser.add_argument("--enable-traces-beta", action="store_true")
    parser.add_argument("--disable-traces-beta", action="store_true")
    parser.add_argument("--enable-detailed-traces", action="store_true")
    parser.add_argument("--disable-detailed-traces", action="store_true")
    parser.add_argument("--disable-galileo", action="store_true")
    parser.add_argument("--accept-content-capture", action="store_true")
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
            print(f"rendered Claude Code O11y assets -> {output_dir}")
        return 0
    except SystemExit:
        raise
    except Exception as exc:
        return command_failed(exc, json_output)


if __name__ == "__main__":
    raise SystemExit(main())
