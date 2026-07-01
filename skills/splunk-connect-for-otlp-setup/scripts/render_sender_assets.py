#!/usr/bin/env python3
"""Render sender assets for Splunk Connect for OTLP."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import stat
import sys
from pathlib import Path


APP_NAME = "splunk-connect-for-otlp"
DEFAULT_RENDER_DIR = "splunk-connect-for-otlp"
SECRET_FLAGS = {
    "--authorization",
    "--hec-token",
    "--hec-token-value",
    "--splunk-token",
    "--token",
}


def reject_direct_secret_flags(argv: list[str]) -> None:
    for arg in argv:
        for flag in SECRET_FLAGS:
            if arg == flag or arg.startswith(flag + "="):
                raise SystemExit(
                    "ERROR: Direct token values are not accepted. Use --hec-token-file."
                )


def parse_args(argv: list[str]) -> argparse.Namespace:
    reject_direct_secret_flags(argv)
    parser = argparse.ArgumentParser(
        description="Render OTel SDK, Collector, and smoke-test sender assets."
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--receiver-host", default="otlp-hf.example.com")
    parser.add_argument("--grpc-port", default="4317")
    parser.add_argument("--http-port", default="4318")
    parser.add_argument("--sender-protocol", choices=("both", "grpc", "http"), default="both")
    parser.add_argument("--sender-tls", choices=("true", "false"), default="true")
    parser.add_argument("--accept-insecure-plaintext-listener", action="store_true")
    parser.add_argument("--hec-token-file", default="/tmp/splunk_otlp_hec_token")
    parser.add_argument("--token-env-var", default="SPLUNK_HEC_TOKEN")
    parser.add_argument("--index", default="otlp_events")
    parser.add_argument("--source", default="otlp")
    parser.add_argument("--sourcetype", default=APP_NAME)
    parser.add_argument("--service-name", default="example-service")
    parser.add_argument("--deployment-environment", default="production")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def positive_port(value: str, option: str) -> int:
    if not re.fullmatch(r"[0-9]+", value or ""):
        die(f"{option} must be a TCP port number.")
    port = int(value)
    if port < 1 or port > 65535:
        die(f"{option} must be between 1 and 65535; port 0 is test-only.")
    return port


def index_name(value: str, option: str) -> None:
    if not re.fullmatch(r"[_A-Za-z0-9][A-Za-z0-9_.-]*", value or ""):
        die(f"{option} contains an invalid Splunk index name: {value!r}.")


def no_newline(value: str, option: str) -> None:
    if "\n" in value or "\r" in value:
        die(f"{option} must not contain newlines.")


def validate(args: argparse.Namespace) -> None:
    positive_port(args.grpc_port, "--grpc-port")
    positive_port(args.http_port, "--http-port")
    index_name(args.index, "--index")
    for value, option in (
        (args.receiver_host, "--receiver-host"),
        (args.hec_token_file, "--hec-token-file"),
        (args.token_env_var, "--token-env-var"),
        (args.source, "--source"),
        (args.sourcetype, "--sourcetype"),
        (args.service_name, "--service-name"),
        (args.deployment_environment, "--deployment-environment"),
    ):
        no_newline(value, option)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", args.token_env_var):
        die("--token-env-var must be a shell environment variable name.")
    if not (
        re.fullmatch(r"[A-Za-z0-9_.-]+", args.receiver_host or "")
        or re.fullmatch(r"\[[A-Za-z0-9:._%-]+\]", args.receiver_host or "")
    ):
        die("--receiver-host must be a host name, IPv4 address, or bracketed IPv6 address without a URL scheme/path.")
    if (
        args.sender_tls == "false"
        and args.receiver_host not in {"127.0.0.1", "localhost", "::1", "[::1]"}
        and not args.accept_insecure_plaintext_listener
    ):
        die(
            "refusing a plaintext sender for a non-loopback receiver; enable TLS "
            "or pass --accept-insecure-plaintext-listener for a lab-only exception."
        )
    for value, option in (
        (args.source, "--source"),
        (args.sourcetype, "--sourcetype"),
        (args.service_name, "--service-name"),
        (args.deployment_environment, "--deployment-environment"),
    ):
        if "," in value:
            die(f"{option} must not contain commas because it is emitted in OTEL_RESOURCE_ATTRIBUTES.")


def scheme(args: argparse.Namespace) -> str:
    return "https" if args.sender_tls == "true" else "http"


def grpc_endpoint(args: argparse.Namespace) -> str:
    return f"{args.receiver_host}:{positive_port(args.grpc_port, '--grpc-port')}"


def http_base(args: argparse.Namespace) -> str:
    return f"{scheme(args)}://{args.receiver_host}:{positive_port(args.http_port, '--http-port')}"


def resource_attributes(args: argparse.Namespace) -> str:
    attrs = {
        "service.name": args.service_name,
        "deployment.environment": args.deployment_environment,
        "com.splunk.index": args.index,
        "com.splunk.source": args.source,
        "com.splunk.sourcetype": args.sourcetype,
        "host.name": "${HOSTNAME}",
    }
    return ",".join(f"{key}={value}" for key, value in attrs.items())


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def render_collector_yaml(args: argparse.Namespace) -> str:
    tls_block = "      insecure: true\n" if args.sender_tls == "false" else "      insecure: false\n"
    token_env = args.token_env_var
    index = json.dumps(args.index)
    sourcetype = json.dumps(args.sourcetype)
    source = json.dumps(args.source)
    grpc = json.dumps(grpc_endpoint(args))
    http = json.dumps(http_base(args))
    return f"""# Rendered by splunk-connect-for-otlp-setup.
# This file references a token environment variable; it does not contain a token value.
receivers:
  otlp:
    protocols:
      grpc:
      http:

processors:
  resource/splunk_metadata:
    attributes:
      - key: com.splunk.index
        value: {index}
        action: upsert
      - key: com.splunk.sourcetype
        value: {sourcetype}
        action: upsert
      - key: com.splunk.source
        value: {source}
        action: upsert
      - key: host.name
        value: "${{env:HOSTNAME}}"
        action: upsert
  batch:

exporters:
  otlp/splunk_connect_grpc:
    endpoint: {grpc}
    headers:
      Authorization: "Splunk ${{env:{token_env}}}"
    tls:
{tls_block}  otlphttp/splunk_connect_http:
    endpoint: {http}
    headers:
      Authorization: "Splunk ${{env:{token_env}}}"
    tls:
{tls_block}
service:
  pipelines:
    logs:
      receivers: [otlp]
      processors: [resource/splunk_metadata, batch]
      exporters: [otlp/splunk_connect_grpc]
    metrics:
      receivers: [otlp]
      processors: [resource/splunk_metadata, batch]
      exporters: [otlp/splunk_connect_grpc]
    traces:
      receivers: [otlp]
      processors: [resource/splunk_metadata, batch]
      exporters: [otlp/splunk_connect_grpc]
"""


def render_sdk_env(args: argparse.Namespace, protocol: str) -> str:
    token_env = args.token_env_var
    endpoint = http_base(args) if protocol == "http" else f"{scheme(args)}://{grpc_endpoint(args)}"
    protocol_value = "http/protobuf" if protocol == "http" else "grpc"
    attributes_prefix = resource_attributes(args).removesuffix("${HOSTNAME}")
    signal_lines = ""
    if protocol == "http":
        signal_lines = f"""
export OTEL_EXPORTER_OTLP_LOGS_ENDPOINT={shlex.quote(http_base(args) + '/v1/logs')}
export OTEL_EXPORTER_OTLP_METRICS_ENDPOINT={shlex.quote(http_base(args) + '/v1/metrics')}
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT={shlex.quote(http_base(args) + '/v1/traces')}
"""
    return f"""#!/usr/bin/env bash
set -euo pipefail

# Source this file locally after creating a chmod-600 HEC token file.
# Token values are loaded from disk at runtime and are never rendered here.
export SPLUNK_HEC_TOKEN_FILE={shlex.quote(args.hec_token_file)}
if [[ ! -f "${{SPLUNK_HEC_TOKEN_FILE}}" || -L "${{SPLUNK_HEC_TOKEN_FILE}}" ]]; then
  echo "ERROR: HEC token path must be a regular, non-symlink file: ${{SPLUNK_HEC_TOKEN_FILE}}" >&2
  return 1 2>/dev/null || exit 1
fi
token_mode="$(stat -c '%a' "${{SPLUNK_HEC_TOKEN_FILE}}" 2>/dev/null || stat -f '%Lp' "${{SPLUNK_HEC_TOKEN_FILE}}" 2>/dev/null || true)"
if [[ ! "${{token_mode}}" =~ ^[0-7]*00$ ]]; then
  echo "ERROR: HEC token file must not have group/other permission bits: ${{SPLUNK_HEC_TOKEN_FILE}}" >&2
  return 1 2>/dev/null || exit 1
fi
token_value="$(cat "${{SPLUNK_HEC_TOKEN_FILE}}")"
token_value="${{token_value#"${{token_value%%[![:space:]]*}}"}}"
token_value="${{token_value%"${{token_value##*[![:space:]]}}"}}"
if [[ -z "${{token_value}}" ]]; then
  echo "ERROR: HEC token file is empty." >&2
  return 1 2>/dev/null || exit 1
fi
export {token_env}="${{token_value}}"
unset token_value
export OTEL_EXPORTER_OTLP_ENDPOINT={shlex.quote(endpoint)}
export OTEL_EXPORTER_OTLP_PROTOCOL={shlex.quote(protocol_value)}
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Splunk ${{{token_env}}}"
export OTEL_RESOURCE_ATTRIBUTES={shlex.quote(attributes_prefix)}"${{HOSTNAME:-unknown}}"
{signal_lines}"""


def render_telemetrygen(args: argparse.Namespace) -> str:
    return """#!/usr/bin/env bash
set -euo pipefail

# telemetrygen accepts OTLP headers on argv, which would expose the HEC token
# to process listings. This generated helper intentionally refuses that path.
echo "ERROR: telemetrygen smoke is not executed because its HEC header would be visible in process arguments." >&2
echo "HANDOFF: Use collector-otlp-sender.yaml or an SDK profile that reads the token file without putting it on argv." >&2
exit 1
"""


def render_readme(args: argparse.Namespace) -> str:
    return f"""# Splunk Connect for OTLP Sender Assets

Receiver host: `{args.receiver_host}`
gRPC endpoint: `{grpc_endpoint(args)}`
HTTP base endpoint: `{http_base(args)}`
Expected index: `{args.index}`

HTTP signal paths:

- `{http_base(args)}/v1/logs`
- `{http_base(args)}/v1/metrics`
- `{http_base(args)}/v1/traces`

Every sender must include:

```text
Authorization: Splunk <HEC_TOKEN>
```

The rendered files reference the local token file path
`{args.hec_token_file}` but do not contain the token value.

`telemetrygen-smoke.sh` is a fail-closed handoff: telemetrygen's header flag
would put the HEC token on argv, so the helper exits nonzero and directs the
operator to the Collector or SDK sender profiles instead.

Route explicitly with OTLP resource attributes:

- `com.splunk.index={args.index}`
- `com.splunk.sourcetype={args.sourcetype}`
- `com.splunk.source={args.source}`
- `host.name=<sender host>`
"""


def metadata(args: argparse.Namespace, files: list[str]) -> dict[str, object]:
    return {
        "app": APP_NAME,
        "receiver": {
            "host": args.receiver_host,
            "grpc_endpoint": grpc_endpoint(args),
            "http_base": http_base(args),
            "http_paths": ["/v1/logs", "/v1/metrics", "/v1/traces"],
            "tls": args.sender_tls == "true",
        },
        "routing": {
            "index": args.index,
            "source": args.source,
            "sourcetype": args.sourcetype,
            "attribute_keys": [
                "com.splunk.index",
                "com.splunk.sourcetype",
                "com.splunk.source",
                "host.name",
            ],
        },
        "secret_handling": {
            "token_file_path_reference": args.hec_token_file,
            "token_env_var": args.token_env_var,
            "token_value_rendered": False,
            "telemetrygen_smoke": "refused_argv_secret_handoff",
        },
        "files": files,
    }


def render(args: argparse.Namespace) -> dict[str, object]:
    validate(args)
    render_dir = Path(args.output_dir).expanduser().resolve() / DEFAULT_RENDER_DIR
    files: list[tuple[str, str, bool]] = [
        ("README.md", render_readme(args), False),
        ("collector-otlp-sender.yaml", render_collector_yaml(args), False),
        ("sdk-env-http.sh", render_sdk_env(args, "http"), True),
        ("sdk-env-grpc.sh", render_sdk_env(args, "grpc"), True),
        ("telemetrygen-smoke.sh", render_telemetrygen(args), True),
    ]
    rels = [name for name, _, _ in files] + ["metadata.json"]
    meta = metadata(args, rels)
    if args.dry_run:
        return meta
    for name, content, executable in files:
        write_file(render_dir / name, content.rstrip() + "\n", executable=executable)
    write_file(render_dir / "metadata.json", json.dumps(meta, indent=2, sort_keys=True) + "\n")
    return meta


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    meta = render(args)
    if args.json or args.dry_run:
        print(json.dumps(meta, indent=2, sort_keys=True))
    else:
        print(f"Rendered sender assets to {Path(args.output_dir).expanduser().resolve() / DEFAULT_RENDER_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
