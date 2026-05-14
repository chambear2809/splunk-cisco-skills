#!/usr/bin/env python3
"""Render Galileo to Splunk integration assets.

The renderer is intentionally offline. It never reads token files and writes
only commands that reference secret file paths.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import sys
from pathlib import Path
from typing import Any


SKILL_NAME = "splunk-galileo-integration"
APPLY_SECTIONS = [
    "hec-service",
    "hec-export",
    "otlp-input",
    "otel-collector",
    "python-runtime",
    "kubernetes-runtime",
    "dashboards",
    "detectors",
]
O11Y_ONLY_SECTIONS = [
    "otel-collector",
    "python-runtime",
    "kubernetes-runtime",
    "dashboards",
    "detectors",
]
SPLUNK_PLATFORM_SECTIONS = {"hec-service", "hec-export", "otlp-input"}
DIRECT_SECRET_FLAGS = {
    "--access-token",
    "--api-key",
    "--api-token",
    "--authorization",
    "--bearer-token",
    "--galileo-api-key",
    "--galileo-bearer-token",
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
                f"ERROR: Direct secret flag {flag} is blocked. Use --galileo-api-key-file, "
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
    parser.add_argument("--project-id", default="")
    parser.add_argument("--project-name", default="")
    parser.add_argument("--log-stream-id", default="")
    parser.add_argument("--log-stream", default="")
    parser.add_argument("--galileo-api-base", default="")
    parser.add_argument("--galileo-otel-endpoint", default="")
    parser.add_argument("--galileo-api-key-file", default="")
    parser.add_argument("--splunk-platform", choices=["enterprise", "cloud"], default="")
    parser.add_argument("--splunk-hec-url", default="")
    parser.add_argument("--splunk-hec-token-file", default="")
    parser.add_argument("--splunk-index", default="")
    parser.add_argument("--splunk-source", default="")
    parser.add_argument("--splunk-sourcetype", default="")
    parser.add_argument("--splunk-host", default="")
    parser.add_argument("--hec-token-name", default="")
    parser.add_argument("--hec-allowed-indexes", default="")
    parser.add_argument("--realm", default="")
    parser.add_argument("--o11y-token-file", default="")
    parser.add_argument("--o11y-only", action="store_true")
    parser.add_argument("--service-name", default="")
    parser.add_argument("--deployment-environment", default="")
    parser.add_argument("--otlp-receiver-host", default="")
    parser.add_argument("--otlp-grpc-port", default="")
    parser.add_argument("--otlp-http-port", default="")
    parser.add_argument("--collector-cluster-name", default="")
    parser.add_argument("--kube-namespace", default="")
    parser.add_argument("--kube-workload", default="")
    parser.add_argument("--runtime-target-dir", default="")
    parser.add_argument("--root-type", choices=["session", "trace", "span"], default="")
    parser.add_argument("--cursor-file", default="")
    parser.add_argument("--since", default="")
    parser.add_argument("--until", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(raw_args)


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


def parse_simple_yaml(text: str) -> dict[str, Any] | None:
    """Parse the simple scalar mapping syntax used by template.example.

    This is a narrow fallback for local systems without PyYAML. It intentionally
    does not claim general YAML support.
    """
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
        key = key.strip()
        value = raw_value.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            return None
        current = stack[-1][1]
        if value == "":
            child: dict[str, Any] = {}
            current[key] = child
            stack.append((indent, child))
            continue
        if value.startswith(("'", '"')) and value.endswith(("'", '"')) and len(value) >= 2:
            value = value[1:-1]
        current[key] = value
    return root


def reject_inline_secrets(node: Any, path: str = "") -> None:
    secret_keys = {
        "access_token",
        "api_key",
        "api_token",
        "authorization",
        "bearer_token",
        "galileo_api_key",
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

    allowed = arg_or_spec("hec_allowed_indexes", "splunk.hec_allowed_indexes", "")
    index = arg_or_spec("splunk_index", "splunk.index", "galileo")
    if not allowed:
        allowed = index

    return {
        "project_id": arg_or_spec("project_id", "galileo.project_id", ""),
        "project_name": arg_or_spec("project_name", "galileo.project_name", "galileo-project"),
        "log_stream_id": arg_or_spec("log_stream_id", "galileo.log_stream_id", ""),
        "log_stream": arg_or_spec("log_stream", "galileo.log_stream", "production"),
        "galileo_api_base": arg_or_spec("galileo_api_base", "galileo.api_base", "https://api.galileo.ai"),
        "galileo_otel_endpoint": arg_or_spec(
            "galileo_otel_endpoint",
            "galileo.otel_endpoint",
            "https://api.galileo.ai/otel/traces",
        ),
        "galileo_api_key_file": arg_or_spec(
            "galileo_api_key_file",
            "secrets.galileo_api_key_file",
            "",
        ),
        "splunk_platform": arg_or_spec("splunk_platform", "splunk.platform", "enterprise"),
        "splunk_hec_url": arg_or_spec("splunk_hec_url", "splunk.hec_url", ""),
        "splunk_hec_token_file": arg_or_spec(
            "splunk_hec_token_file",
            "secrets.splunk_hec_token_file",
            "",
        ),
        "splunk_index": index,
        "splunk_source": arg_or_spec("splunk_source", "splunk.source", "galileo"),
        "splunk_sourcetype": arg_or_spec(
            "splunk_sourcetype",
            "splunk.sourcetype",
            "galileo:observe:json",
        ),
        "splunk_host": arg_or_spec("splunk_host", "splunk.host", ""),
        "hec_token_name": arg_or_spec("hec_token_name", "splunk.hec_token_name", "galileo_observe"),
        "hec_allowed_indexes": allowed,
        "realm": arg_or_spec("realm", "splunk_observability.realm", ""),
        "o11y_only": bool(args.o11y_only)
        or str(get_nested(spec, "splunk_observability.o11y_only", "")).lower()
        in {"1", "yes", "true"},
        "o11y_token_file": arg_or_spec("o11y_token_file", "secrets.o11y_token_file", ""),
        "service_name": arg_or_spec("service_name", "runtime.service_name", "galileo-instrumented-app"),
        "deployment_environment": arg_or_spec(
            "deployment_environment",
            "runtime.deployment_environment",
            "production",
        ),
        "otlp_receiver_host": arg_or_spec(
            "otlp_receiver_host",
            "otlp.receiver_host",
            "otlp.example.com",
        ),
        "otlp_grpc_port": arg_or_spec("otlp_grpc_port", "otlp.grpc_port", "4317"),
        "otlp_http_port": arg_or_spec("otlp_http_port", "otlp.http_port", "4318"),
        "collector_cluster_name": arg_or_spec(
            "collector_cluster_name",
            "collector.cluster_name",
            "galileo-apps",
        ),
        "kube_namespace": arg_or_spec("kube_namespace", "kubernetes.namespace", "default"),
        "kube_workload": arg_or_spec("kube_workload", "kubernetes.workload", ""),
        "runtime_target_dir": arg_or_spec("runtime_target_dir", "runtime.target_dir", ""),
        "root_type": arg_or_spec("root_type", "hec_export.root_type", "trace"),
        "cursor_file": arg_or_spec("cursor_file", "hec_export.cursor_file", ""),
        "since": arg_or_spec("since", "hec_export.since", ""),
        "until": arg_or_spec("until", "hec_export.until", ""),
    }


def selected_sections(value: str, *, o11y_only: bool = False) -> list[str]:
    if not value or value == "all":
        if o11y_only:
            return list(O11Y_ONLY_SECTIONS)
        return list(APPLY_SECTIONS)
    sections = [item.strip() for item in value.split(",") if item.strip()]
    unknown = sorted(set(sections) - set(APPLY_SECTIONS))
    if unknown:
        raise SystemExit(f"ERROR: Unknown apply section(s): {', '.join(unknown)}")
    if o11y_only:
        blocked = sorted(set(sections) & SPLUNK_PLATFORM_SECTIONS)
        if blocked:
            raise SystemExit(
                "ERROR: --o11y-only cannot select Splunk Platform section(s): "
                + ", ".join(blocked)
            )
    return sections


def write_text(path: Path, text: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if executable:
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


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


def render_scripts(output_dir: Path, config: dict[str, Any], sections: list[str]) -> dict[str, str]:
    scripts: dict[str, str] = {}
    scripts_dir = output_dir / "scripts"

    hec_service = f"""{script_header()}
{require_file_var("SPLUNK_HEC_TOKEN_FILE", config["splunk_hec_token_file"], "--splunk-hec-token-file")}
exec bash "${{PROJECT_ROOT}}/skills/splunk-hec-service-setup/scripts/setup.sh" \\
  --platform {shell_quote(config["splunk_platform"])} \\
  --phase apply \\
  --token-name {shell_quote(config["hec_token_name"])} \\
  --description {shell_quote("Managed for Galileo Observe export")} \\
  --default-index {shell_quote(config["splunk_index"])} \\
  --allowed-indexes {shell_quote(config["hec_allowed_indexes"])} \\
  --source {shell_quote(config["splunk_source"])} \\
  --sourcetype {shell_quote(config["splunk_sourcetype"])} \\
  --token-file "${{SPLUNK_HEC_TOKEN_FILE}}"
"""
    write_text(scripts_dir / "apply-hec-service.sh", hec_service, executable=True)
    scripts["hec-service"] = "scripts/apply-hec-service.sh"

    hec_export = f"""{script_header()}
{require_file_var("GALILEO_API_KEY_FILE", config["galileo_api_key_file"], "--galileo-api-key-file")}
{require_file_var("SPLUNK_HEC_TOKEN_FILE", config["splunk_hec_token_file"], "--splunk-hec-token-file")}
SPLUNK_HEC_URL="${{SPLUNK_HEC_URL:-{shell_double_default(config["splunk_hec_url"])}}}"
if [[ -z "${{SPLUNK_HEC_URL}}" ]]; then
  echo "ERROR: SPLUNK_HEC_URL is required. Re-render with --splunk-hec-url or set the env var." >&2
  exit 1
fi
cmd=(python3 "${{PROJECT_ROOT}}/skills/splunk-galileo-integration/scripts/galileo_to_splunk_hec.py"
  --galileo-api-base {shell_quote(config["galileo_api_base"])}
  --galileo-api-key-file "${{GALILEO_API_KEY_FILE}}"
  --project-id {shell_quote(config["project_id"])}
  --log-stream-id {shell_quote(config["log_stream_id"])}
  --root-type {shell_quote(config["root_type"])}
  --splunk-hec-url "${{SPLUNK_HEC_URL}}"
  --splunk-hec-token-file "${{SPLUNK_HEC_TOKEN_FILE}}"
  --splunk-index {shell_quote(config["splunk_index"])}
  --splunk-source {shell_quote(config["splunk_source"])}
  --splunk-sourcetype {shell_quote(config["splunk_sourcetype"])})
"""
    if config["splunk_host"]:
        hec_export += f'cmd+=(--splunk-host {shell_quote(config["splunk_host"])})\n'
    if config["cursor_file"]:
        hec_export += f'cmd+=(--cursor-file {shell_quote(config["cursor_file"])})\n'
    if config["since"]:
        hec_export += f'cmd+=(--since {shell_quote(config["since"])})\n'
    if config["until"]:
        hec_export += f'cmd+=(--until {shell_quote(config["until"])})\n'
    hec_export += 'exec "${cmd[@]}"\n'
    write_text(scripts_dir / "apply-hec-export.sh", hec_export, executable=True)
    scripts["hec-export"] = "scripts/apply-hec-export.sh"

    otlp_input = f"""{script_header()}
{require_file_var("SPLUNK_HEC_TOKEN_FILE", config["splunk_hec_token_file"], "--splunk-hec-token-file")}
exec bash "${{PROJECT_ROOT}}/skills/splunk-connect-for-otlp-setup/scripts/setup.sh" \\
  --render \\
  --configure-input \\
  --input-name "galileo-otlp" \\
  --expected-index {shell_quote(config["splunk_index"])} \\
  --receiver-host {shell_quote(config["otlp_receiver_host"])} \\
  --grpc-port {shell_quote(config["otlp_grpc_port"])} \\
  --http-port {shell_quote(config["otlp_http_port"])} \\
  --hec-token-file "${{SPLUNK_HEC_TOKEN_FILE}}" \\
  --output-dir "${{OUTPUT_DIR}}/delegated/splunk-connect-for-otlp"
"""
    write_text(scripts_dir / "apply-otlp-input.sh", otlp_input, executable=True)
    scripts["otlp-input"] = "scripts/apply-otlp-input.sh"

    if config["o11y_only"]:
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
    else:
        otel_collector = f"""{script_header()}
{require_file_var("O11Y_TOKEN_FILE", config["o11y_token_file"], "--o11y-token-file")}
{require_file_var("SPLUNK_HEC_TOKEN_FILE", config["splunk_hec_token_file"], "--splunk-hec-token-file")}
SPLUNK_HEC_URL="${{SPLUNK_HEC_URL:-{shell_double_default(config["splunk_hec_url"])}}}"
if [[ -z {shell_quote(config["realm"])} ]]; then
  echo "ERROR: --realm is required for the otel-collector handoff." >&2
  exit 1
fi
exec bash "${{PROJECT_ROOT}}/skills/splunk-observability-otel-collector-setup/scripts/setup.sh" \\
  --render-k8s \\
  --render-linux \\
  --render-platform-hec-helper \\
  --realm {shell_quote(config["realm"])} \\
  --cluster-name {shell_quote(config["collector_cluster_name"])} \\
  --deployment-environment {shell_quote(config["deployment_environment"])} \\
  --service-name {shell_quote(config["service_name"])} \\
  --o11y-token-file "${{O11Y_TOKEN_FILE}}" \\
  --platform-hec-token-file "${{SPLUNK_HEC_TOKEN_FILE}}" \\
  --platform-hec-url "${{SPLUNK_HEC_URL}}" \\
  --platform-hec-index {shell_quote(config["splunk_index"])} \\
  --output-dir "${{OUTPUT_DIR}}/delegated/splunk-otel-collector"
"""
    write_text(scripts_dir / "apply-otel-collector.sh", otel_collector, executable=True)
    scripts["otel-collector"] = "scripts/apply-otel-collector.sh"

    python_runtime = f"""{script_header()}
TARGET_DIR="${{RUNTIME_TARGET_DIR:-{shell_double_default(config["runtime_target_dir"])}}}"
if [[ -z "${{TARGET_DIR}}" ]]; then
  echo "Set RUNTIME_TARGET_DIR to copy runtime/python-opentelemetry-galileo.py into an app tree." >&2
  echo "Rendered snippet: ${{OUTPUT_DIR}}/runtime/python-opentelemetry-galileo.py" >&2
  exit 0
fi
mkdir -p "${{TARGET_DIR}}"
cp "${{OUTPUT_DIR}}/runtime/python-opentelemetry-galileo.py" "${{TARGET_DIR}}/galileo_splunk_observability.py"
echo "Installed Galileo runtime snippet into ${{TARGET_DIR}}/galileo_splunk_observability.py"
"""
    write_text(scripts_dir / "apply-python-runtime.sh", python_runtime, executable=True)
    scripts["python-runtime"] = "scripts/apply-python-runtime.sh"

    kubernetes_runtime = f"""{script_header()}
NAMESPACE="${{KUBE_NAMESPACE:-{shell_double_default(config["kube_namespace"])}}}"
WORKLOAD="${{KUBE_WORKLOAD:-{shell_double_default(config["kube_workload"])}}}"
if [[ -z "${{WORKLOAD}}" ]]; then
  echo "Set KUBE_WORKLOAD to apply the Galileo runtime ConfigMap and annotation helper." >&2
  echo "Rendered manifest: ${{OUTPUT_DIR}}/runtime/kubernetes-galileo-env-configmap.yaml" >&2
  exit 0
fi
kubectl -n "${{NAMESPACE}}" apply -f "${{OUTPUT_DIR}}/runtime/kubernetes-galileo-env-configmap.yaml"
kubectl -n "${{NAMESPACE}}" annotate deployment "${{WORKLOAD}}" instrumentation.opentelemetry.io/inject-python=true --overwrite
"""
    write_text(scripts_dir / "apply-kubernetes-runtime.sh", kubernetes_runtime, executable=True)
    scripts["kubernetes-runtime"] = "scripts/apply-kubernetes-runtime.sh"

    dashboards = f"""{script_header()}
{require_file_var("O11Y_TOKEN_FILE", config["o11y_token_file"], "--o11y-token-file")}
if [[ -z {shell_quote(config["realm"])} ]]; then
  echo "ERROR: --realm is required for dashboard apply." >&2
  exit 1
fi
exec bash "${{PROJECT_ROOT}}/skills/splunk-observability-dashboard-builder/scripts/setup.sh" \\
  --apply \\
  --spec "${{OUTPUT_DIR}}/dashboards/galileo-dashboard.yaml" \\
  --realm {shell_quote(config["realm"])} \\
  --token-file "${{O11Y_TOKEN_FILE}}" \\
  --output-dir "${{OUTPUT_DIR}}/delegated/dashboards"
"""
    write_text(scripts_dir / "apply-dashboards.sh", dashboards, executable=True)
    scripts["dashboards"] = "scripts/apply-dashboards.sh"

    detectors = f"""{script_header()}
{require_file_var("O11Y_TOKEN_FILE", config["o11y_token_file"], "--o11y-token-file")}
if [[ -z {shell_quote(config["realm"])} ]]; then
  echo "ERROR: --realm is required for detector apply." >&2
  exit 1
fi
exec bash "${{PROJECT_ROOT}}/skills/splunk-observability-native-ops/scripts/setup.sh" \\
  --apply \\
  --spec "${{OUTPUT_DIR}}/detectors/galileo-detectors.yaml" \\
  --realm {shell_quote(config["realm"])} \\
  --token-file "${{O11Y_TOKEN_FILE}}" \\
  --output-dir "${{OUTPUT_DIR}}/delegated/detectors"
"""
    write_text(scripts_dir / "apply-detectors.sh", detectors, executable=True)
    scripts["detectors"] = "scripts/apply-detectors.sh"

    apply_all_lines = [script_header(), "sections=(" + " ".join(shell_quote(s) for s in sections) + ")\n"]
    apply_all_lines.append(
        """for section in "${sections[@]}"; do
  case "${section}" in
    hec-service) "${SCRIPT_DIR}/apply-hec-service.sh" ;;
    hec-export) "${SCRIPT_DIR}/apply-hec-export.sh" ;;
    otlp-input) "${SCRIPT_DIR}/apply-otlp-input.sh" ;;
    otel-collector) "${SCRIPT_DIR}/apply-otel-collector.sh" ;;
    python-runtime) "${SCRIPT_DIR}/apply-python-runtime.sh" ;;
    kubernetes-runtime) "${SCRIPT_DIR}/apply-kubernetes-runtime.sh" ;;
    dashboards) "${SCRIPT_DIR}/apply-dashboards.sh" ;;
    detectors) "${SCRIPT_DIR}/apply-detectors.sh" ;;
  esac
done
"""
    )
    write_text(scripts_dir / "apply-selected.sh", "".join(apply_all_lines), executable=True)
    scripts["selected"] = "scripts/apply-selected.sh"
    return scripts


def render_runtime(output_dir: Path, config: dict[str, Any]) -> None:
    write_text(
        output_dir / "runtime/python-opentelemetry-env.sh",
        f"""# Source this file in a local shell, then export the secret values from files.
export GALILEO_PROJECT={shell_quote(config["project_name"])}
export GALILEO_LOG_STREAM={shell_quote(config["log_stream"])}
export OTEL_SERVICE_NAME={shell_quote(config["service_name"])}
export OTEL_RESOURCE_ATTRIBUTES={shell_quote("deployment.environment=" + config["deployment_environment"])}
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT={shell_quote(config["galileo_otel_endpoint"])}
export GALILEO_API_KEY_FILE={shell_quote(config["galileo_api_key_file"])}
""",
    )
    write_text(
        output_dir / "runtime/python-opentelemetry-galileo.py",
        f'''"""Minimal Galileo OpenTelemetry/OpenInference setup.

Import and call configure_galileo_tracing() before constructing LLM clients.
The API key is read from GALILEO_API_KEY_FILE at runtime.
"""

from __future__ import annotations

import os
from pathlib import Path


def _read_secret_file(env_name: str) -> str:
    path = os.environ.get(env_name, "")
    if not path:
        raise RuntimeError(f"{{env_name}} is required")
    return Path(path).read_text(encoding="utf-8").strip()


def configure_galileo_tracing() -> None:
    os.environ.setdefault("GALILEO_PROJECT", {config["project_name"]!r})
    os.environ.setdefault("GALILEO_LOG_STREAM", {config["log_stream"]!r})
    os.environ.setdefault("OTEL_SERVICE_NAME", {config["service_name"]!r})
    os.environ.setdefault("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", {config["galileo_otel_endpoint"]!r})
    if "GALILEO_API_KEY" not in os.environ:
        os.environ["GALILEO_API_KEY"] = _read_secret_file("GALILEO_API_KEY_FILE")

    from galileo import otel
    from opentelemetry import trace as trace_api
    from opentelemetry.sdk import trace as trace_sdk
    from opentelemetry.sdk.resources import Resource

    tracer_provider = trace_sdk.TracerProvider(
        resource=Resource.create(
            {{
                "service.name": os.environ["OTEL_SERVICE_NAME"],
                "deployment.environment": {config["deployment_environment"]!r},
            }}
        )
    )
    otel.add_galileo_span_processor(tracer_provider, otel.GalileoSpanProcessor())
    trace_api.set_tracer_provider(tracer_provider)
''',
    )
    write_text(
        output_dir / "runtime/kubernetes-galileo-env-configmap.yaml",
        f"""apiVersion: v1
kind: ConfigMap
metadata:
  name: galileo-otel-env
  namespace: {config["kube_namespace"]}
data:
  GALILEO_PROJECT: {json.dumps(config["project_name"])}
  GALILEO_LOG_STREAM: {json.dumps(config["log_stream"])}
  OTEL_SERVICE_NAME: {json.dumps(config["service_name"])}
  OTEL_EXPORTER_OTLP_TRACES_ENDPOINT: {json.dumps(config["galileo_otel_endpoint"])}
  OTEL_RESOURCE_ATTRIBUTES: {json.dumps("deployment.environment=" + config["deployment_environment"])}
""",
    )


def render_splunk_platform(output_dir: Path, config: dict[str, Any]) -> None:
    write_text(
        output_dir / "splunk-platform/galileo-hec-export.env.example",
        f"""GALILEO_API_KEY_FILE={shell_quote(config["galileo_api_key_file"])}
SPLUNK_HEC_TOKEN_FILE={shell_quote(config["splunk_hec_token_file"])}
SPLUNK_HEC_URL={shell_quote(config["splunk_hec_url"])}
GALILEO_PROJECT_ID={shell_quote(config["project_id"])}
GALILEO_LOG_STREAM_ID={shell_quote(config["log_stream_id"])}
SPLUNK_INDEX={shell_quote(config["splunk_index"])}
SPLUNK_SOURCE={shell_quote(config["splunk_source"])}
SPLUNK_SOURCETYPE={shell_quote(config["splunk_sourcetype"])}
""",
    )
    write_json(
        output_dir / "splunk-platform/hec-event-sample.json",
        {
            "time": 1770000000.0,
            "source": config["splunk_source"],
            "sourcetype": config["splunk_sourcetype"],
            "index": config["splunk_index"],
            "event": {
                "galileo_record_key": "project:log-stream:trace:record",
                "galileo_project_id": config["project_id"] or "<project-id>",
                "galileo_log_stream_id": config["log_stream_id"] or "<log-stream-id>",
                "galileo_record_id": "<record-id>",
                "galileo_record_type": config["root_type"],
                "redacted_input": "<redacted>",
                "redacted_output": "<redacted>",
                "metrics": {},
            },
        },
    )
    write_text(
        output_dir / "splunk-platform/search-examples.spl",
        f"""sourcetype="{config["splunk_sourcetype"]}" index="{config["splunk_index"]}"
| stats count by galileo_record_type status_code

sourcetype="{config["splunk_sourcetype"]}" index="{config["splunk_index"]}"
| stats latest(updated_at) as latest_update by galileo_project_id galileo_log_stream_id
""",
    )


def render_otel(output_dir: Path, config: dict[str, Any]) -> None:
    write_text(
        output_dir / "otel/collector-galileo-fanout.yaml",
        f"""receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:{config["otlp_grpc_port"]}
      http:
        endpoint: 0.0.0.0:{config["otlp_http_port"]}

exporters:
  otlphttp/galileo:
    endpoint: {config["galileo_otel_endpoint"]}
    headers:
      Galileo-API-Key: ${{env:GALILEO_API_KEY}}
      project: {config["project_name"]}
      logstream: {config["log_stream"]}

service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [otlphttp/galileo]
""",
    )
    write_text(
        output_dir / "otel/python-sender-env.sh",
        f"""export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://{config["otlp_receiver_host"]}:{config["otlp_http_port"]}/v1/traces
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
export OTEL_SERVICE_NAME={shell_quote(config["service_name"])}
export OTEL_RESOURCE_ATTRIBUTES={shell_quote("deployment.environment=" + config["deployment_environment"])}
""",
    )


def render_o11y_specs(output_dir: Path, config: dict[str, Any]) -> None:
    realm = config["realm"] or "us0"
    service = config["service_name"]
    env = config["deployment_environment"]
    write_text(
        output_dir / "dashboards/galileo-dashboard.yaml",
        f"""api_version: splunk-observability-dashboard-builder/v1
mode: classic-api
realm: {realm}
dashboard_group:
  name: Galileo Observe
  description: Galileo Observe application telemetry.
dashboard:
  name: Galileo Observe Operations
  description: Runtime service and Galileo export health.
  chart_density: DEFAULT
  filters:
    variables:
      - property: service.name
        alias: Service
        value:
          - {service}
        required: true
        restricted: false
charts:
  - id: trace-rate
    name: Trace rate
    type: TimeSeriesChart
    plot_type: LineChart
    row: 0
    column: 0
    width: 6
    height: 1
    program_text: |
      data('spans.count', filter=filter('service.name', '{service}')).sum().publish(label='spans')
  - id: errors
    name: Span errors
    type: TimeSeriesChart
    plot_type: AreaChart
    row: 0
    column: 6
    width: 6
    height: 1
    program_text: |
      data('errors.count', filter=filter('service.name', '{service}')).sum().publish(label='errors')
  - id: notes
    name: Operating notes
    type: Text
    row: 1
    column: 0
    width: 12
    height: 1
    markdown: |
      Galileo REST exports land in Splunk Platform as sourcetype {config["splunk_sourcetype"]}.
      OpenTelemetry runtime data is filtered by service.name={service} and deployment.environment={env}.
""",
    )
    write_text(
        output_dir / "detectors/galileo-detectors.yaml",
        f"""api_version: splunk-observability-native-ops/v1
realm: {realm}
detectors:
  - name: Galileo span errors
    description: Error spans from Galileo-instrumented services exceeded the starter threshold.
    program_text: |
      errors = data('errors.count', filter=filter('service.name', '{service}')).sum().publish(label='errors')
      detect(when(errors > threshold(5))).publish('galileo_errors')
    tags:
      - galileo
      - {env}
    rules:
      - detect_label: galileo_errors
        severity: Major
        description: Investigate Galileo-instrumented service errors.
  - name: Galileo trace volume drop
    description: Trace volume dropped to zero for a running service.
    program_text: |
      spans = data('spans.count', filter=filter('service.name', '{service}')).sum().publish(label='spans')
      detect(when(spans < threshold(1))).publish('galileo_trace_volume_low')
    tags:
      - galileo
      - {env}
    rules:
      - detect_label: galileo_trace_volume_low
        severity: Warning
        description: Confirm the runtime still exports OpenTelemetry spans.
""",
    )


def build_apply_plan(
    config: dict[str, Any], scripts: dict[str, str], sections: list[str], output_dir: Path
) -> dict[str, Any]:
    targets = {
        "hec-service": "splunk-hec-service-setup",
        "hec-export": "splunk-galileo-integration",
        "otlp-input": "splunk-connect-for-otlp-setup",
        "otel-collector": "splunk-observability-otel-collector-setup",
        "python-runtime": "splunk-galileo-integration",
        "kubernetes-runtime": "splunk-galileo-integration",
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
            "galileo_api_key_file": config["galileo_api_key_file"],
            "splunk_hec_token_file": config["splunk_hec_token_file"],
            "o11y_token_file": config["o11y_token_file"],
        },
        "modes": {
            "o11y_only": config["o11y_only"],
            "splunk_platform_hec_enabled": not config["o11y_only"],
        },
        "paths": {
            "apply_plan": "apply-plan.json",
            "coverage_report": "coverage-report.json",
            "handoff": "handoff.md",
            "runtime": "runtime/",
            "splunk_platform": "splunk-platform/",
            "otel": "otel/",
            "scripts": "scripts/",
        },
    }


def build_coverage_report(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "api_version": f"{SKILL_NAME}/coverage/v1",
        "status": "rendered",
        "secret_values_rendered": False,
        "coverage": {
            "galileo_rest_export_to_splunk_hec": {
                "status": "automated",
                "script": "scripts/galileo_to_splunk_hec.py",
                "delegates": ["splunk-hec-service-setup"],
            },
            "galileo_opentelemetry_openinference": {
                "status": "rendered_handoff",
                "assets": ["runtime/", "otel/"],
                "delegates": [
                    "splunk-connect-for-otlp-setup",
                    "splunk-observability-otel-collector-setup",
                ],
            },
            "splunk_observability_operations": {
                "status": "delegated",
                "delegates": [
                    "splunk-observability-dashboard-builder",
                    "splunk-observability-native-ops",
                ],
            },
        },
        "defaults": {
            "sourcetype": config["splunk_sourcetype"],
            "index": config["splunk_index"],
            "root_type": config["root_type"],
            "o11y_only": config["o11y_only"],
        },
    }


def render_handoff(output_dir: Path, config: dict[str, Any], scripts: dict[str, str]) -> None:
    lines = [
        "# Galileo Splunk Handoff",
        "",
        "Rendered assets are offline by default and keep secret values in local files.",
        "",
    ]
    if config["o11y_only"]:
        lines.extend(
            [
                "Mode: Splunk Observability Cloud-only. Default apply skips Splunk Platform HEC/OTLP sections.",
                "",
            ]
        )
    lines.append("## Apply Sections")
    for section in APPLY_SECTIONS:
        lines.append(f"- `{section}`: `{scripts[section]}`")
    lines.extend(
        [
            "",
            "## Delegation Targets",
            "- `hec-service` -> `splunk-hec-service-setup`",
            "- `otlp-input` -> `splunk-connect-for-otlp-setup`",
            "- `otel-collector` -> `splunk-observability-otel-collector-setup`",
            "- `dashboards` -> `splunk-observability-dashboard-builder`",
            "- `detectors` -> `splunk-observability-native-ops`",
            "",
            "## First Validation",
            f"bash {scripts['selected'].replace('scripts/', str(output_dir / 'scripts') + '/')}",
            "",
            "## Splunk Search Starter",
            f'`sourcetype="{config["splunk_sourcetype"]}" index="{config["splunk_index"]}" | stats count by galileo_record_type`',
            "",
        ]
    )
    write_text(output_dir / "handoff.md", "\n".join(lines))


def maybe_copy_bridge(output_dir: Path) -> None:
    source = Path(__file__).with_name("galileo_to_splunk_hec.py")
    if source.is_file():
        target = output_dir / "scripts/galileo_to_splunk_hec.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def render(args: argparse.Namespace) -> dict[str, Any]:
    spec = load_spec(args.spec)
    config = merge_config(args, spec)
    sections = selected_sections(args.apply, o11y_only=config["o11y_only"])
    output_dir = Path(args.output_dir).expanduser().resolve()
    scripts = {section: f"scripts/apply-{section}.sh" for section in APPLY_SECTIONS}
    scripts["selected"] = "scripts/apply-selected.sh"
    dry_plan = build_apply_plan(config, scripts, sections, output_dir)
    if args.dry_run:
        return dry_plan

    output_dir.mkdir(parents=True, exist_ok=True)
    render_runtime(output_dir, config)
    render_splunk_platform(output_dir, config)
    render_otel(output_dir, config)
    render_o11y_specs(output_dir, config)
    scripts = render_scripts(output_dir, config, sections)
    maybe_copy_bridge(output_dir)
    apply_plan = build_apply_plan(config, scripts, sections, output_dir)
    coverage = build_coverage_report(config)
    write_json(output_dir / "apply-plan.json", apply_plan)
    write_json(output_dir / "coverage-report.json", coverage)
    render_handoff(output_dir, config, scripts)
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
        print(f"Rendered Galileo Splunk assets to {payload['output_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
