#!/usr/bin/env bash
set -euo pipefail

collector_config=""
collector_binary=""
traces_pipeline="traces"
lemonade_receiver="otlp"
production_mode=false

usage() {
  cat <<'EOF'
Validate a staged Lemonade collector configuration.

Usage:
  validate.sh --collector-config PATH [--collector-binary PATH]
              [--traces-pipeline NAME] [--lemonade-receiver NAME]
              [--production]

--production requires an explicit absolute path to the exact installed
collector binary and runs its native `validate` subcommand.
Static validation requires Python 3 and PyYAML (`python3-yaml` on Debian).
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --collector-config|--collector-binary|--traces-pipeline|--lemonade-receiver)
      [[ $# -ge 2 && -n "${2:-}" ]] || {
        echo "ERROR: $1 requires a nonempty value" >&2
        exit 2
      }
      case "$1" in
        --collector-config) collector_config="$2" ;;
        --collector-binary) collector_binary="$2" ;;
        --traces-pipeline) traces_pipeline="$2" ;;
        --lemonade-receiver) lemonade_receiver="$2" ;;
      esac
      shift 2
      ;;
    --production) production_mode=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

[[ -n "$collector_config" && -f "$collector_config" ]] || {
  echo "ERROR: --collector-config must name a staged file" >&2
  exit 1
}

python3 - "$collector_config" "$traces_pipeline" "$lemonade_receiver" <<'PY'
import ipaddress
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
try:
    import yaml
except ModuleNotFoundError as exc:
    raise SystemExit(
        "ERROR: PyYAML is required; on Debian install python3-yaml"
    ) from exc

path = Path(sys.argv[1])
traces_pipeline = sys.argv[2]
lemonade_receiver = sys.argv[3]
try:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
except yaml.YAMLError as exc:
    raise SystemExit(f"ERROR: invalid collector YAML: {exc}") from exc
if not isinstance(doc, dict):
    raise SystemExit("ERROR: collector root must be a mapping")

secret_placeholder_pattern = re.compile(
    r"\$\{(?:(?:env):)?[A-Z][A-Z0-9_]{0,127}\}"
)
sensitive_field_keys = {
    "accesstoken",
    "apikey",
    "authorization",
    "clientsecret",
    "password",
    "secret",
    "splunkaccesstoken",
    "token",
    "xauthtoken",
    "xsftoken",
}
sensitive_header_keys = {
    "apikey",
    "authorization",
    "splunkaccesstoken",
    "xapikey",
    "xauthtoken",
    "xsftoken",
}


def normalized_key(value):
    if not isinstance(value, str):
        return ""
    return re.sub(r"[^a-z0-9]", "", value.lower())


def validate_secret_placeholders(value, *, parent_is_headers=False):
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = normalized_key(key)
            sensitive = normalized in sensitive_field_keys or (
                parent_is_headers and normalized in sensitive_header_keys
            )
            if sensitive:
                if not isinstance(child, str) or not secret_placeholder_pattern.fullmatch(
                    child
                ):
                    raise SystemExit(
                        "ERROR: credential-bearing Collector fields must use an "
                        "exact uppercase environment placeholder"
                    )
                continue
            validate_secret_placeholders(
                child, parent_is_headers=normalized == "headers"
            )
    elif isinstance(value, list):
        for child in value:
            validate_secret_placeholders(child)


validate_secret_placeholders(doc)


def require_mapping(parent, key, location):
    value = parent.get(key)
    if not isinstance(value, dict):
        raise SystemExit(f"ERROR: expected mapping at {location}.{key}")
    return value


def require_pipeline_list(pipeline, key, location):
    value = pipeline.get(key)
    if not isinstance(value, list) or not value:
        raise SystemExit(f"ERROR: {location}.{key} must be a nonempty list")
    if not all(isinstance(item, str) and item for item in value):
        raise SystemExit(f"ERROR: {location}.{key} must contain nonempty strings")
    if len(value) != len(set(value)):
        raise SystemExit(f"ERROR: {location}.{key} contains duplicate components")
    return value


def validated_scalar(value, label):
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"ERROR: {label} must be nonempty")
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise SystemExit(f"ERROR: {label} contains control characters")
    return value


validated_scalar(traces_pipeline, "selected traces pipeline")
validated_scalar(lemonade_receiver, "selected Lemonade receiver")

service = require_mapping(doc, "service", "collector")
pipelines = require_mapping(service, "pipelines", "service")
receivers = require_mapping(doc, "receivers", "collector")
processors = require_mapping(doc, "processors", "collector")
exporters = require_mapping(doc, "exporters", "collector")
connectors = doc.get("connectors", {})
if not isinstance(connectors, dict):
    raise SystemExit("ERROR: collector.connectors must be a mapping when present")
receiver_definitions = {**receivers, **connectors}
exporter_definitions = {**exporters, **connectors}

for pipeline_name, pipeline in pipelines.items():
    location = f"service.pipelines.{pipeline_name}"
    if not isinstance(pipeline, dict):
        raise SystemExit(f"ERROR: {location} must be a mapping")
    for field, definitions in (
        ("receivers", receiver_definitions),
        ("processors", processors),
        ("exporters", exporter_definitions),
    ):
        components = require_pipeline_list(pipeline, field, location)
        undefined = [component for component in components if component not in definitions]
        if undefined:
            raise SystemExit(
                f"ERROR: {location}.{field} references undefined component(s): "
                + ", ".join(undefined)
            )

traces = pipelines.get(traces_pipeline)
if not isinstance(traces, dict):
    raise SystemExit(f"ERROR: missing service.pipelines.{traces_pipeline}")
trace_processors = traces["processors"]
privacy_name = "transform/lemonade_resource_privacy"
if trace_processors.count(privacy_name) != 1:
    raise SystemExit("ERROR: traces pipeline must contain exactly one Lemonade privacy transform")
privacy_index = trace_processors.index(privacy_name)
batch_indexes = [
    index for index, component in enumerate(trace_processors)
    if component.split("/", 1)[0] == "batch"
]
if batch_indexes and privacy_index > min(batch_indexes):
    raise SystemExit("ERROR: Lemonade privacy transform must run before batch")

privacy = processors.get(privacy_name)
if not isinstance(privacy, dict) or set(privacy) != {"error_mode", "trace_statements"}:
    raise SystemExit("ERROR: Lemonade privacy transform has an unknown top-level shape")
if privacy.get("error_mode") != "propagate":
    raise SystemExit("ERROR: Lemonade privacy transform error_mode must be propagate")
groups = privacy.get("trace_statements")
if not isinstance(groups, list) or len(groups) != 1:
    raise SystemExit("ERROR: Lemonade privacy transform must have one trace statement group")
group = groups[0]
if not isinstance(group, dict) or set(group) != {"context", "statements"}:
    raise SystemExit("ERROR: Lemonade privacy transform statement group has an unknown shape")
if group.get("context") != "span":
    raise SystemExit("ERROR: Lemonade privacy transform context must be span")
statements = group.get("statements")
if not isinstance(statements, list) or len(statements) != 4 or not all(
    isinstance(statement, str) for statement in statements
):
    raise SystemExit("ERROR: Lemonade privacy transform must contain four ordered statements")

json_string = r'("(?:\\.|[^"\\])*")'
first_pattern = re.compile(
    r'^set\(resource\.attributes\["deployment\.environment\.name"\], '
    + f'(?P<environment>{json_string})'
    + r'\) where resource\.attributes\["service\.name"\] == '
    + f'(?P<service>{json_string})'
    + r' and resource\.attributes\["deployment\.environment\.name"\] == nil$'
)
matched = first_pattern.fullmatch(statements[0])
if matched is None:
    raise SystemExit("ERROR: first Lemonade privacy statement is not the managed form")
try:
    environment = json.loads(matched.group("environment"))
    service_name = json.loads(matched.group("service"))
except json.JSONDecodeError as exc:
    raise SystemExit("ERROR: Lemonade privacy transform contains an invalid string literal") from exc
validated_scalar(environment, "managed deployment environment")
validated_scalar(service_name, "managed service name")
environment_literal = json.dumps(environment)
service_literal = json.dumps(service_name)
expected_statements = [
    (
        'set(resource.attributes["deployment.environment.name"], '
        f'{environment_literal}) where resource.attributes["service.name"] '
        f'== {service_literal} and '
        'resource.attributes["deployment.environment.name"] == nil'
    ),
    (
        'set(resource.attributes["deployment.environment"], '
        f'{environment_literal}) where resource.attributes["service.name"] '
        f'== {service_literal} and '
        'resource.attributes["deployment.environment"] == nil'
    ),
    (
        'set(span.status.message, "[REDACTED]") where span.status.code == '
        f'STATUS_CODE_ERROR and resource.attributes["service.name"] == {service_literal}'
    ),
    (
        'set(span.attributes["error.type"], "lemonade.error") where '
        'span.status.code == STATUS_CODE_ERROR and '
        'span.attributes["error.type"] == nil and '
        f'resource.attributes["service.name"] == {service_literal}'
    ),
]
if statements != expected_statements:
    raise SystemExit("ERROR: Lemonade privacy statements differ from the managed ordered form")

if lemonade_receiver not in traces["receivers"]:
    raise SystemExit("ERROR: selected Lemonade receiver is not in the traces pipeline")
if not isinstance(receivers.get(lemonade_receiver), dict):
    raise SystemExit("ERROR: selected Lemonade receiver is not defined")
receiver = receivers[lemonade_receiver]
protocols = receiver.get("protocols")
if not isinstance(protocols, dict) or not protocols:
    raise SystemExit("ERROR: selected Lemonade receiver must define protocols")

placeholder_pattern = re.compile(r"\$\{(?:(?:env):)?([A-Za-z_][A-Za-z0-9_]*)\}")


def resolve_placeholder(value, endpoint):
    matched_placeholder = placeholder_pattern.fullmatch(value)
    if not matched_placeholder:
        return value
    variable = matched_placeholder.group(1)
    raw = os.environ.get(variable, "")
    if not raw or raw != raw.strip():
        raise SystemExit(
            f"ERROR: receiver {lemonade_receiver} endpoint uses {endpoint}; "
            f"set {variable} to a nonempty, whitespace-free deployed value "
            "for static validation"
        )
    return raw


for protocol_name, protocol in protocols.items():
    if not isinstance(protocol, dict):
        raise SystemExit(
            f"ERROR: receiver {lemonade_receiver} protocol {protocol_name} must be a mapping"
        )
    endpoint = protocol.get("endpoint")
    if not isinstance(endpoint, str) or not endpoint or endpoint != endpoint.strip():
        raise SystemExit(
            f"ERROR: receiver {lemonade_receiver} protocol {protocol_name} needs an explicit endpoint"
        )
    if any(unicodedata.category(character) == "Cc" for character in endpoint):
        raise SystemExit("ERROR: receiver endpoint contains control characters")
    if any(character in endpoint for character in "/?#@"):
        raise SystemExit(f"ERROR: receiver endpoint is not a host:port value: {endpoint}")
    if endpoint.startswith("["):
        endpoint_match = re.fullmatch(r"\[([^\]]+)\]:(.+)", endpoint)
        if endpoint_match is None:
            raise SystemExit(f"ERROR: invalid bracketed receiver endpoint: {endpoint}")
        host, port_text = endpoint_match.groups()
    else:
        host, separator, port_text = endpoint.rpartition(":")
        if not separator or not host or ":" in host:
            raise SystemExit(f"ERROR: receiver endpoint must be host:port: {endpoint}")
    host = resolve_placeholder(host, endpoint)
    if host.startswith("[") or host.endswith("]"):
        if (
            not (host.startswith("[") and host.endswith("]"))
            or "[" in host[1:-1]
            or "]" in host[1:-1]
        ):
            raise SystemExit(f"ERROR: receiver endpoint has invalid host brackets: {endpoint}")
        host = host[1:-1]
    port_text = resolve_placeholder(port_text, endpoint)
    if not re.fullmatch(r"[0-9]+", port_text):
        raise SystemExit(f"ERROR: receiver endpoint has an invalid port: {endpoint}")
    port = int(port_text)
    if not 1 <= port <= 65535:
        raise SystemExit(f"ERROR: receiver endpoint port is out of range: {endpoint}")
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host == "localhost"
    if not loopback:
        raise SystemExit(
            f"ERROR: receiver {lemonade_receiver} protocol {protocol_name} "
            f"is not loopback-bound: {host}"
        )
print("Static Lemonade collector validation passed")
PY

if [[ "$production_mode" == true && -z "$collector_binary" ]]; then
  echo "ERROR: --production requires --collector-binary with the exact installed binary" >&2
  exit 1
fi

if [[ -n "$collector_binary" ]]; then
  if [[ "$production_mode" == true && "$collector_binary" != /* ]]; then
    echo "ERROR: --production requires an absolute --collector-binary path" >&2
    exit 1
  fi
  [[ -f "$collector_binary" && -x "$collector_binary" ]] || {
    echo "ERROR: collector binary is not executable: $collector_binary" >&2
    exit 1
  }
  "$collector_binary" validate --config="$collector_config"
fi
