#!/usr/bin/env python3
"""Render Galileo platform readiness and Splunk integration assets.

The renderer is intentionally offline. It never reads token files and writes
only commands that reference secret file paths.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import shutil
import stat
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse


SKILL_NAME = "galileo-platform-setup"
SOURCE_PROJECT_ROOT = Path(__file__).resolve().parents[3]
APPLY_SECTIONS = [
    "readiness",
    "object-lifecycle",
    "luna-scorers",
    "observe-export",
    "observe-runtime",
    "protect-runtime",
    "evaluate-assets",
    "multimodal-assets",
    "observability-controls",
    "splunk-hec",
    "splunk-otlp",
    "otel-collector",
    "dashboards",
    "detectors",
]
O11Y_ONLY_SECTIONS = [
    "readiness",
    "object-lifecycle",
    "luna-scorers",
    "observe-runtime",
    "protect-runtime",
    "evaluate-assets",
    "multimodal-assets",
    "observability-controls",
    "otel-collector",
    "dashboards",
    "detectors",
]
SPLUNK_PLATFORM_SECTIONS = {"observe-export", "splunk-hec", "splunk-otlp"}
DIRECT_SECRET_FLAGS = {
    "--access-token",
    "--api-key",
    "--api-token",
    "--authorization",
    "--bearer-token",
    "--galileo-api-key",
    "--galileo-bearer-token",
    "--galileo-webhook-token",
    "--hec-token",
    "--o11y-token",
    "--password",
    "--sf-token",
    "--splunk-hec-token",
    "--token",
}

EMBEDDED_PRIVATE_SECRET_READER = r'''def _read_private_secret(path_value: str, label: str) -> str:
    """Read one stable UTF-8 line from an owner-only, non-symlink file."""
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "geteuid"):
        raise RuntimeError(
            f"{label} cannot be read safely: O_NOFOLLOW/geteuid is unavailable"
        )
    path = Path(path_value).expanduser()
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RuntimeError(
            f"{label} must be a readable, non-symlink regular file: {path}"
        ) from exc
    try:
        before = os.fstat(descriptor)
        mode = stat.S_IMODE(before.st_mode)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise RuntimeError(f"{label} must be a single-link regular file: {path}")
        if before.st_uid != os.geteuid():
            raise RuntimeError(f"{label} must be owned by the current user: {path}")
        if mode & 0o077:
            raise RuntimeError(
                f"{label} permissions must be 0600 or stricter: {path} has {mode:04o}"
            )
        if not 1 <= before.st_size <= 65536:
            raise RuntimeError(f"{label} size must be between 1 and 65536 bytes: {path}")
        chunks = []
        remaining = 65537
        while remaining:
            chunk = os.read(descriptor, min(remaining, 8192))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        data = b"".join(chunks)
        before_fingerprint = (
            before.st_dev, before.st_ino, before.st_mode, before.st_uid, before.st_size,
            before.st_mtime_ns, before.st_ctime_ns, before.st_nlink,
        )
        after_fingerprint = (
            after.st_dev, after.st_ino, after.st_mode, after.st_uid, after.st_size,
            after.st_mtime_ns, after.st_ctime_ns, after.st_nlink,
        )
        if before_fingerprint != after_fingerprint or len(data) != before.st_size:
            raise RuntimeError(f"{label} changed while it was read: {path}")
    finally:
        os.close(descriptor)
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"{label} must contain UTF-8 text: {path}") from exc
    if len(lines) != 1 or "\x00" in lines[0] or not lines[0].strip():
        raise RuntimeError(f"{label} must contain exactly one non-empty line: {path}")
    return lines[0].strip()
'''


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
    parser.add_argument("--lifecycle-manifest", default="")
    parser.add_argument("--dataset-dir", default="")
    parser.add_argument("--prompt-manifest", default="")
    parser.add_argument("--experiment-manifest", default="")
    parser.add_argument("--protect-stage-manifest", default="")
    parser.add_argument("--metrics", default="")
    parser.add_argument("--luna-scorer-map", default="")
    parser.add_argument("--luna-list-only", choices=["true", "false"], default="")
    parser.add_argument("--luna-recompute", choices=["true", "false"], default="")
    parser.add_argument("--luna-strict", choices=["true", "false"], default="")
    parser.add_argument("--luna-recompute-limit", default="")
    parser.add_argument("--galileo-api-base", default="")
    parser.add_argument("--galileo-console-url", default="")
    parser.add_argument("--galileo-otel-endpoint", default="")
    parser.add_argument("--experiment-id", default="")
    parser.add_argument("--metrics-testing-id", default="")
    parser.add_argument("--multimodal-enabled", choices=["true", "false"], default="")
    parser.add_argument("--multimodal-input-modalities", default="")
    parser.add_argument("--multimodal-output-modalities", default="")
    parser.add_argument("--multimodal-capture-methods", default="")
    parser.add_argument("--multimodal-quality-metrics", default="")
    parser.add_argument("--multimodal-asset-policy", default="")
    parser.add_argument("--allow-raw-media-in-splunk", action="store_true")
    parser.add_argument(
        "--export-format", choices=["jsonl", "jsonl_flat", "csv"], default=""
    )
    parser.add_argument(
        "--export-computed-metrics-only", choices=["true", "false"], default=""
    )
    parser.add_argument(
        "--include-code-metric-metadata", choices=["true", "false"], default=""
    )
    parser.add_argument("--redact", choices=["true", "false"], default="")
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
    api_base = arg_or_spec("galileo_api_base", "galileo.api_base", "")
    console_url = arg_or_spec("galileo_console_url", "galileo.console_url", "")
    if not api_base and not console_url:
        raise SystemExit(
            "ERROR: Galileo instance URL intake is required. Pass --galileo-console-url "
            "with the user's Galileo console URL, or pass --galileo-api-base only when "
            "the user explicitly confirmed that API base."
        )
    if console_url:
        validate_galileo_root_url(console_url, "Galileo console URL")
    if api_base:
        api_base = normalize_api_base(api_base)
    else:
        api_base = derive_api_base(console_url)
    otel_endpoint = arg_or_spec("galileo_otel_endpoint", "galileo.otel_endpoint", "")
    if not otel_endpoint:
        otel_endpoint = api_base.rstrip("/") + "/otel/traces"
    else:
        otel_endpoint = normalize_http_endpoint(otel_endpoint, "Galileo OTLP endpoint")

    multimodal_enabled_value = args.multimodal_enabled or str(
        get_nested(spec, "multimodal.enabled", "true") or "true"
    )
    allow_raw_media = bool(args.allow_raw_media_in_splunk) or str(
        get_nested(spec, "multimodal.allow_raw_media_in_splunk", "false") or "false"
    ).lower() in {"1", "yes", "true"}
    export_format = arg_or_spec("export_format", "hec_export.export_format", "jsonl")
    if export_format not in {"csv", "jsonl", "jsonl_flat"}:
        raise SystemExit(
            "ERROR: hec_export.export_format must be csv, jsonl, or jsonl_flat"
        )
    export_computed_metrics_only = str(
        args.export_computed_metrics_only
        or get_nested(spec, "hec_export.export_computed_metrics_only", "false")
        or "false"
    ).lower() in {"1", "yes", "true"}
    include_code_metric_metadata = str(
        args.include_code_metric_metadata
        or get_nested(spec, "hec_export.include_code_metric_metadata", "false")
        or "false"
    ).lower() in {"1", "yes", "true"}
    if export_computed_metrics_only and export_format == "jsonl_flat":
        raise SystemExit(
            "ERROR: export_computed_metrics_only is not supported with jsonl_flat"
        )
    return {
        "project_id": arg_or_spec("project_id", "galileo.project_id", ""),
        "project_name": arg_or_spec("project_name", "galileo.project_name", "galileo-project"),
        "log_stream_id": arg_or_spec("log_stream_id", "galileo.log_stream_id", ""),
        "log_stream": arg_or_spec("log_stream", "galileo.log_stream", "production"),
        "lifecycle_manifest": arg_or_spec(
            "lifecycle_manifest",
            "galileo.lifecycle_manifest",
            "",
        ),
        "dataset_dir": arg_or_spec("dataset_dir", "galileo.dataset_dir", ""),
        "prompt_manifest": arg_or_spec("prompt_manifest", "galileo.prompt_manifest", ""),
        "experiment_manifest": arg_or_spec(
            "experiment_manifest",
            "galileo.experiment_manifest",
            "",
        ),
        "protect_stage_manifest": arg_or_spec(
            "protect_stage_manifest",
            "galileo.protect_stage_manifest",
            "",
        ),
        "metrics": arg_or_spec("metrics", "galileo.metrics", ""),
        "luna_scorer_map": arg_or_spec(
            "luna_scorer_map",
            "galileo.luna_scorer_map",
            "",
        ),
        "luna_list_only": str(
            args.luna_list_only or get_nested(spec, "galileo.luna_list_only", "false") or "false"
        ).lower()
        in {"1", "yes", "true"},
        "luna_recompute": str(
            args.luna_recompute or get_nested(spec, "galileo.luna_recompute", "false") or "false"
        ).lower()
        in {"1", "yes", "true"},
        "luna_strict": str(
            args.luna_strict or get_nested(spec, "galileo.luna_strict", "false") or "false"
        ).lower()
        in {"1", "yes", "true"},
        "luna_recompute_limit": arg_or_spec(
            "luna_recompute_limit",
            "galileo.luna_recompute_limit",
            "100",
        ),
        "galileo_api_base": api_base,
        "galileo_console_url": console_url,
        "galileo_otel_endpoint": otel_endpoint,
        "experiment_id": arg_or_spec("experiment_id", "galileo.experiment_id", ""),
        "metrics_testing_id": arg_or_spec("metrics_testing_id", "galileo.metrics_testing_id", ""),
        "export_format": export_format,
        "export_computed_metrics_only": export_computed_metrics_only,
        "include_code_metric_metadata": include_code_metric_metadata,
        "redact": arg_or_spec("redact", "hec_export.redact", "true").lower() not in {"0", "false", "no"},
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
        "controls_inventory_file": str(
            get_nested(
                spec,
                "observability_controls.inventory_file",
                "./galileo-platform-rendered/controls/control-intake.example.json",
            )
            or ""
        ),
        "controls_export_root_type": str(
            get_nested(spec, "observability_controls.export_root_type_for_evidence", "span") or "span"
        ),
        "controls_expected_fields": str(
            get_nested(
                spec,
                "observability_controls.expected_fields",
                "control_name,step,stage,execution,source,action,evaluator,selector_path,matched,confidence",
            )
            or ""
        ),
        "multimodal_enabled": str(multimodal_enabled_value).lower() not in {"0", "false", "no"},
        "multimodal_input_modalities": arg_or_spec(
            "multimodal_input_modalities",
            "multimodal.input_modalities",
            "image,audio,document",
        ),
        "multimodal_output_modalities": arg_or_spec(
            "multimodal_output_modalities",
            "multimodal.output_modalities",
            "image,audio,document,text",
        ),
        "multimodal_capture_methods": arg_or_spec(
            "multimodal_capture_methods",
            "multimodal.capture_methods",
            "galileo_logger_external_url,galileo_logger_file_upload,langchain_handler",
        ),
        "multimodal_quality_metrics": arg_or_spec(
            "multimodal_quality_metrics",
            "multimodal.quality_metrics",
            "visual_quality,visual_fidelity,interruption_detection",
        ),
        "multimodal_asset_policy": arg_or_spec(
            "multimodal_asset_policy",
            "multimodal.splunk_asset_policy",
            "metadata_only_no_raw_media",
        ),
        "multimodal_allow_raw_media_in_splunk": allow_raw_media,
    }


def validate_galileo_root_url(value: str, label: str) -> Any:
    raw = value.strip()
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw):
        raw = "https://" + raw
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SystemExit(f"ERROR: {label} must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise SystemExit(f"ERROR: {label} must not contain credentials")
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise SystemExit(
            f"ERROR: {label} must not contain a path, parameters, query, or fragment"
        )
    try:
        parsed.port
    except ValueError as exc:
        raise SystemExit(f"ERROR: {label} contains an invalid port") from exc
    if parsed.scheme == "http":
        host = parsed.hostname.lower()
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host == "localhost" or host.endswith(".localhost")
        if not loopback:
            raise SystemExit(f"ERROR: {label} must use HTTPS outside loopback testing")
    return parsed


def normalize_api_base(api_base: str) -> str:
    parsed = validate_galileo_root_url(api_base, "Galileo API base")
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", "")).rstrip("/")


def normalize_http_endpoint(value: str, label: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SystemExit(f"ERROR: {label} must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.params or parsed.query or parsed.fragment:
        raise SystemExit(f"ERROR: {label} contains unsafe URL components")
    try:
        parsed.port
    except ValueError as exc:
        raise SystemExit(f"ERROR: {label} contains an invalid port") from exc
    if parsed.scheme == "http":
        host = parsed.hostname.lower()
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host == "localhost" or host.endswith(".localhost")
        if not loopback:
            raise SystemExit(f"ERROR: {label} must use HTTPS outside loopback testing")
    return value.strip().rstrip("/")


def derive_api_base(console_url: str) -> str:
    raw = console_url.strip()
    if not raw:
        raise SystemExit("ERROR: Galileo console URL is required")
    parsed = validate_galileo_root_url(raw, "Galileo console URL")
    host = parsed.hostname.lower()
    if host == "app.galileo.ai":
        api_host = "api.galileo.ai"
    elif host.startswith("console."):
        api_host = "api." + host[len("console.") :]
    elif host.startswith("console-"):
        api_host = "api-" + host[len("console-") :]
    elif host.startswith("api.") or host.startswith("api-"):
        api_host = host
    else:
        raise SystemExit(
            "ERROR: Cannot derive the Galileo API host from this console URL. "
            "Pass --galileo-api-base with the user-confirmed API base."
        )
    try:
        port = parsed.port
    except ValueError as exc:
        raise SystemExit("ERROR: Galileo console URL contains an invalid port") from exc
    netloc = api_host + (f":{port}" if port is not None else "")
    return urlunparse((parsed.scheme, netloc, "", "", "", "")).rstrip("/")


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


def csv_values(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def script_header() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-__SOURCE_PROJECT_ROOT__}"
""".replace("__SOURCE_PROJECT_ROOT__", shell_double_default(str(SOURCE_PROJECT_ROOT)))


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

    readiness = f"""{script_header()}
HEALTH_URL="${{GALILEO_HEALTH_URL:-{shell_double_default(config["galileo_api_base"].rstrip("/") + "/v2/healthcheck")}}}"
echo "Galileo healthcheck endpoint: ${{HEALTH_URL}}"
if ! command -v curl >/dev/null 2>&1; then
  echo "ERROR: curl is required for Galileo readiness validation." >&2
  exit 1
fi
curl -fsS --max-time 10 "${{HEALTH_URL}}"
echo
"""
    write_text(scripts_dir / "apply-readiness.sh", readiness, executable=True)
    scripts["readiness"] = "scripts/apply-readiness.sh"

    object_lifecycle = f"""{script_header()}
{require_file_var("GALILEO_API_KEY_FILE", config["galileo_api_key_file"], "--galileo-api-key-file")}
cmd=(python3 "${{PROJECT_ROOT}}/skills/galileo-platform-setup/scripts/galileo_object_lifecycle.py"
  --galileo-api-key-file "${{GALILEO_API_KEY_FILE}}"
  --project-name {shell_quote(config["project_name"])}
  --log-stream-name {shell_quote(config["log_stream"])}
  --api-base {shell_quote(config["galileo_api_base"])}
  --ownership-ledger "${{OUTPUT_DIR}}/lifecycle/object-lifecycle-ownership.json"
  --output "${{OUTPUT_DIR}}/lifecycle/object-lifecycle-result.json")
"""
    if config["project_id"]:
        object_lifecycle += f'cmd+=(--project-id {shell_quote(config["project_id"])})\n'
    if config["log_stream_id"]:
        object_lifecycle += f'cmd+=(--log-stream-id {shell_quote(config["log_stream_id"])})\n'
    if config["galileo_console_url"]:
        object_lifecycle += f'cmd+=(--console-url {shell_quote(config["galileo_console_url"])})\n'
    if config["lifecycle_manifest"]:
        object_lifecycle += f'cmd+=(--manifest {shell_quote(config["lifecycle_manifest"])})\n'
    else:
        object_lifecycle += 'cmd+=(--manifest "${OUTPUT_DIR}/lifecycle/object-lifecycle-manifest.example.json")\n'
    if config["dataset_dir"]:
        object_lifecycle += f'cmd+=(--dataset-dir {shell_quote(config["dataset_dir"])})\n'
    if config["prompt_manifest"]:
        object_lifecycle += f'cmd+=(--prompt-manifest {shell_quote(config["prompt_manifest"])})\n'
    if config["experiment_manifest"]:
        object_lifecycle += f'cmd+=(--experiment-manifest {shell_quote(config["experiment_manifest"])})\n'
    if config["protect_stage_manifest"]:
        object_lifecycle += f'cmd+=(--protect-stage-manifest {shell_quote(config["protect_stage_manifest"])})\n'
    if config["metrics"]:
        object_lifecycle += f'cmd+=(--metrics {shell_quote(config["metrics"])})\n'
    object_lifecycle += 'exec "${cmd[@]}"\n'
    write_text(scripts_dir / "apply-object-lifecycle.sh", object_lifecycle, executable=True)
    scripts["object-lifecycle"] = "scripts/apply-object-lifecycle.sh"

    cleanup_object_lifecycle = f"""{script_header()}
{require_file_var("GALILEO_API_KEY_FILE", config["galileo_api_key_file"], "--galileo-api-key-file")}
cmd=(python3 "${{PROJECT_ROOT}}/skills/galileo-platform-setup/scripts/galileo_object_lifecycle.py"
  --cleanup-created
  --galileo-api-key-file "${{GALILEO_API_KEY_FILE}}"
  --api-base {shell_quote(config["galileo_api_base"])}
  --ownership-ledger "${{OUTPUT_DIR}}/lifecycle/object-lifecycle-ownership.json"
  --output "${{OUTPUT_DIR}}/lifecycle/object-lifecycle-cleanup-result.json")
"""
    if config["galileo_console_url"]:
        cleanup_object_lifecycle += (
            f'cmd+=(--console-url {shell_quote(config["galileo_console_url"])})\n'
        )
    cleanup_object_lifecycle += 'exec "${cmd[@]}"\n'
    write_text(
        scripts_dir / "cleanup-object-lifecycle.sh",
        cleanup_object_lifecycle,
        executable=True,
    )

    luna_scorers = f"""{script_header()}
{require_file_var("GALILEO_API_KEY_FILE", config["galileo_api_key_file"], "--galileo-api-key-file")}
cmd=(python3 "${{PROJECT_ROOT}}/skills/galileo-platform-setup/scripts/galileo_luna_scorers.py"
  --galileo-api-key-file "${{GALILEO_API_KEY_FILE}}"
  --api-base {shell_quote(config["galileo_api_base"])}
  --project-id {shell_quote(config["project_id"])}
  --log-stream-id {shell_quote(config["log_stream_id"])}
  --lifecycle-result "${{OUTPUT_DIR}}/lifecycle/object-lifecycle-result.json"
  --output "${{OUTPUT_DIR}}/lifecycle/luna-scorer-settings-result.json")
"""
    if config["luna_scorer_map"]:
        luna_scorers += f'cmd+=(--scorer-map {shell_quote(config["luna_scorer_map"])})\n'
    else:
        luna_scorers += 'cmd+=(--scorer-map "${OUTPUT_DIR}/lifecycle/luna-scorer-map.example.json")\n'
    if config["luna_recompute"]:
        luna_scorers += "cmd+=(--recompute)\n"
    if config["luna_list_only"]:
        luna_scorers += "cmd+=(--list-only)\n"
    if config["luna_strict"]:
        luna_scorers += "cmd+=(--strict)\n"
    if config["luna_recompute_limit"]:
        luna_scorers += f'cmd+=(--recompute-limit {shell_quote(config["luna_recompute_limit"])})\n'
    luna_scorers += 'exec "${cmd[@]}"\n'
    write_text(scripts_dir / "apply-luna-scorers.sh", luna_scorers, executable=True)
    scripts["luna-scorers"] = "scripts/apply-luna-scorers.sh"

    splunk_hec = f"""{script_header()}
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
    write_text(scripts_dir / "apply-splunk-hec.sh", splunk_hec, executable=True)
    scripts["splunk-hec"] = "scripts/apply-splunk-hec.sh"

    observe_export = f"""{script_header()}
{require_file_var("GALILEO_API_KEY_FILE", config["galileo_api_key_file"], "--galileo-api-key-file")}
{require_file_var("SPLUNK_HEC_TOKEN_FILE", config["splunk_hec_token_file"], "--splunk-hec-token-file")}
SPLUNK_HEC_URL="${{SPLUNK_HEC_URL:-{shell_double_default(config["splunk_hec_url"])}}}"
if [[ -z "${{SPLUNK_HEC_URL}}" ]]; then
  echo "ERROR: SPLUNK_HEC_URL is required. Re-render with --splunk-hec-url or set the env var." >&2
  exit 1
fi
cmd=(python3 "${{PROJECT_ROOT}}/skills/galileo-platform-setup/scripts/galileo_to_splunk_hec.py"
  --galileo-api-base {shell_quote(config["galileo_api_base"])}
  --galileo-api-key-file "${{GALILEO_API_KEY_FILE}}"
  --project-id {shell_quote(config["project_id"])}
  --log-stream-id {shell_quote(config["log_stream_id"])}
  --experiment-id {shell_quote(config["experiment_id"])}
  --metrics-testing-id {shell_quote(config["metrics_testing_id"])}
  --export-format {shell_quote(config["export_format"])}
  --redact {shell_quote("true" if config["redact"] else "false")}
  --root-type {shell_quote(config["root_type"])}
  --splunk-hec-url "${{SPLUNK_HEC_URL}}"
  --splunk-hec-token-file "${{SPLUNK_HEC_TOKEN_FILE}}"
  --splunk-index {shell_quote(config["splunk_index"])}
  --splunk-source {shell_quote(config["splunk_source"])}
    --splunk-sourcetype {shell_quote(config["splunk_sourcetype"])})
"""
    if config["export_computed_metrics_only"]:
        observe_export += "cmd+=(--export-computed-metrics-only)\n"
    if config["include_code_metric_metadata"]:
        observe_export += "cmd+=(--include-code-metric-metadata)\n"
    if config["splunk_host"]:
        observe_export += f'cmd+=(--splunk-host {shell_quote(config["splunk_host"])})\n'
    if config["cursor_file"]:
        observe_export += f'cmd+=(--cursor-file {shell_quote(config["cursor_file"])})\n'
    if config["since"]:
        observe_export += f'cmd+=(--since {shell_quote(config["since"])})\n'
    if config["until"]:
        observe_export += f'cmd+=(--until {shell_quote(config["until"])})\n'
    observe_export += 'exec "${cmd[@]}"\n'
    write_text(scripts_dir / "apply-observe-export.sh", observe_export, executable=True)
    scripts["observe-export"] = "scripts/apply-observe-export.sh"

    splunk_otlp = f"""{script_header()}
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
    write_text(scripts_dir / "apply-splunk-otlp.sh", splunk_otlp, executable=True)
    scripts["splunk-otlp"] = "scripts/apply-splunk-otlp.sh"

    if config["o11y_only"]:
        otel_collector = f"""{script_header()}
{require_file_var("O11Y_TOKEN_FILE", config["o11y_token_file"], "--o11y-token-file")}
REALM={shell_quote(config["realm"])}
if [[ -z "${{REALM}}" ]]; then
  echo "ERROR: --realm is required for the otel-collector handoff." >&2
  exit 1
fi
exec bash "${{PROJECT_ROOT}}/skills/splunk-observability-otel-collector-setup/scripts/setup.sh" \\
  --render-k8s \\
  --render-linux \\
  --realm "${{REALM}}" \\
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
REALM={shell_quote(config["realm"])}
if [[ -z "${{REALM}}" ]]; then
  echo "ERROR: --realm is required for the otel-collector handoff." >&2
  exit 1
fi
exec bash "${{PROJECT_ROOT}}/skills/splunk-observability-otel-collector-setup/scripts/setup.sh" \\
  --render-k8s \\
  --render-linux \\
  --render-platform-hec-helper \\
  --realm "${{REALM}}" \\
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

    observe_runtime = f"""{script_header()}
TARGET_DIR="${{RUNTIME_TARGET_DIR:-{shell_double_default(config["runtime_target_dir"])}}}"
if [[ -n "${{TARGET_DIR}}" ]]; then
  mkdir -p "${{TARGET_DIR}}"
  cp "${{OUTPUT_DIR}}/runtime/python-opentelemetry-galileo.py" "${{TARGET_DIR}}/galileo_splunk_observability.py"
  echo "Installed Galileo Observe runtime snippet into ${{TARGET_DIR}}/galileo_splunk_observability.py"
else
  echo "Set RUNTIME_TARGET_DIR to copy runtime/python-opentelemetry-galileo.py into an app tree." >&2
  echo "Rendered snippet: ${{OUTPUT_DIR}}/runtime/python-opentelemetry-galileo.py" >&2
fi
NAMESPACE="${{KUBE_NAMESPACE:-{shell_double_default(config["kube_namespace"])}}}"
WORKLOAD="${{KUBE_WORKLOAD:-{shell_double_default(config["kube_workload"])}}}"
if [[ -z "${{WORKLOAD}}" ]]; then
  echo "Set KUBE_WORKLOAD to apply the Galileo runtime ConfigMap and annotation helper." >&2
  echo "Rendered manifest: ${{OUTPUT_DIR}}/runtime/kubernetes-galileo-env-configmap.yaml" >&2
  if [[ -z "${{TARGET_DIR}}" ]]; then
    exit 1
  fi
  exit 0
fi
kubectl -n "${{NAMESPACE}}" apply -f "${{OUTPUT_DIR}}/runtime/kubernetes-galileo-env-configmap.yaml"
kubectl -n "${{NAMESPACE}}" annotate deployment "${{WORKLOAD}}" instrumentation.opentelemetry.io/inject-python=true --overwrite
"""
    write_text(scripts_dir / "apply-observe-runtime.sh", observe_runtime, executable=True)
    scripts["observe-runtime"] = "scripts/apply-observe-runtime.sh"

    protect_runtime = f"""{script_header()}
TARGET_DIR="${{RUNTIME_TARGET_DIR:-{shell_double_default(config["runtime_target_dir"])}}}"
if [[ -z "${{TARGET_DIR}}" ]]; then
  echo "Set RUNTIME_TARGET_DIR to copy runtime/python-galileo-protect.py into an app tree." >&2
  echo "Rendered snippet: ${{OUTPUT_DIR}}/runtime/python-galileo-protect.py" >&2
  exit 1
fi
mkdir -p "${{TARGET_DIR}}"
cp "${{OUTPUT_DIR}}/runtime/python-galileo-protect.py" "${{TARGET_DIR}}/galileo_protect_runtime.py"
echo "Installed Galileo Protect runtime snippet into ${{TARGET_DIR}}/galileo_protect_runtime.py"
"""
    write_text(scripts_dir / "apply-protect-runtime.sh", protect_runtime, executable=True)
    scripts["protect-runtime"] = "scripts/apply-protect-runtime.sh"

    evaluate_assets = f"""{script_header()}
echo "ERROR: evaluate-assets is a render-only handoff; use object-lifecycle for documented API mutations." >&2
echo "Review ${{OUTPUT_DIR}}/evaluate/ and complete the documented console/API handoff." >&2
exit 2
"""
    write_text(scripts_dir / "apply-evaluate-assets.sh", evaluate_assets, executable=True)
    scripts["evaluate-assets"] = "scripts/apply-evaluate-assets.sh"

    multimodal_assets = f"""{script_header()}
echo "ERROR: multimodal-assets is a render-only handoff, not an automated apply." >&2
echo "Review ${{OUTPUT_DIR}}/multimodal/ and the rendered validation searches." >&2
exit 2
"""
    write_text(scripts_dir / "apply-multimodal-assets.sh", multimodal_assets, executable=True)
    scripts["multimodal-assets"] = "scripts/apply-multimodal-assets.sh"

    observability_controls = f"""{script_header()}
echo "ERROR: observability-controls is a render-only console handoff; no documented CRUD API is available." >&2
echo "Review ${{OUTPUT_DIR}}/controls/ and validate exported control-span evidence." >&2
exit 2
"""
    write_text(
        scripts_dir / "apply-observability-controls.sh",
        observability_controls,
        executable=True,
    )
    scripts["observability-controls"] = "scripts/apply-observability-controls.sh"

    dashboards = f"""{script_header()}
{require_file_var("O11Y_TOKEN_FILE", config["o11y_token_file"], "--o11y-token-file")}
REALM={shell_quote(config["realm"])}
if [[ -z "${{REALM}}" ]]; then
  echo "ERROR: --realm is required for dashboard apply." >&2
  exit 1
fi
exec bash "${{PROJECT_ROOT}}/skills/splunk-observability-dashboard-builder/scripts/setup.sh" \\
  --apply \\
  --spec "${{OUTPUT_DIR}}/dashboards/galileo-dashboard.yaml" \\
  --realm "${{REALM}}" \\
  --token-file "${{O11Y_TOKEN_FILE}}" \\
  --output-dir "${{OUTPUT_DIR}}/delegated/dashboards"
"""
    write_text(scripts_dir / "apply-dashboards.sh", dashboards, executable=True)
    scripts["dashboards"] = "scripts/apply-dashboards.sh"

    detectors = f"""{script_header()}
{require_file_var("O11Y_TOKEN_FILE", config["o11y_token_file"], "--o11y-token-file")}
REALM={shell_quote(config["realm"])}
if [[ -z "${{REALM}}" ]]; then
  echo "ERROR: --realm is required for detector apply." >&2
  exit 1
fi
exec bash "${{PROJECT_ROOT}}/skills/splunk-observability-native-ops/scripts/setup.sh" \\
  --apply \\
  --spec "${{OUTPUT_DIR}}/detectors/galileo-detectors.yaml" \\
  --realm "${{REALM}}" \\
  --token-file "${{O11Y_TOKEN_FILE}}" \\
  --output-dir "${{OUTPUT_DIR}}/delegated/detectors"
"""
    write_text(scripts_dir / "apply-detectors.sh", detectors, executable=True)
    scripts["detectors"] = "scripts/apply-detectors.sh"

    apply_all_lines = [script_header(), "sections=(" + " ".join(shell_quote(s) for s in sections) + ")\n"]
    apply_all_lines.append(
        """for section in "${sections[@]}"; do
  case "${section}" in
    readiness) "${SCRIPT_DIR}/apply-readiness.sh" ;;
    object-lifecycle) "${SCRIPT_DIR}/apply-object-lifecycle.sh" ;;
    luna-scorers) "${SCRIPT_DIR}/apply-luna-scorers.sh" ;;
    observe-export) "${SCRIPT_DIR}/apply-observe-export.sh" ;;
    observe-runtime) "${SCRIPT_DIR}/apply-observe-runtime.sh" ;;
    protect-runtime) "${SCRIPT_DIR}/apply-protect-runtime.sh" ;;
    evaluate-assets) "${SCRIPT_DIR}/apply-evaluate-assets.sh" ;;
    multimodal-assets) "${SCRIPT_DIR}/apply-multimodal-assets.sh" ;;
    observability-controls) "${SCRIPT_DIR}/apply-observability-controls.sh" ;;
    splunk-hec) "${SCRIPT_DIR}/apply-splunk-hec.sh" ;;
    splunk-otlp) "${SCRIPT_DIR}/apply-splunk-otlp.sh" ;;
    otel-collector) "${SCRIPT_DIR}/apply-otel-collector.sh" ;;
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
export GALILEO_API_BASE={shell_quote(config["galileo_api_base"])}
export GALILEO_API_URL={shell_quote(config["galileo_api_base"])}
export GALILEO_CONSOLE_URL={shell_quote(config["galileo_console_url"])}
""",
    )
    write_text(
        output_dir / "runtime/codex-notify-galileo-handoff.md",
        f"""# Codex Notify to Galileo Runtime Handoff

Use this handoff when Codex itself should write completed interactive turns into
this Galileo project and log stream.

## What This Solves

Configuring the Galileo MCP server lets Codex call Galileo MCP tools. It does
not automatically send Codex conversations, tool calls, or turn results into a
Galileo log stream.

For interactive Codex, the proven runtime path is a fail-soft `notify` bridge:

1. Codex finishes a turn and invokes its configured `notify` command.
2. The notifier parses the newest completed turn from
   `CODEX_HOME/sessions/YYYY/MM/DD/rollout-*.jsonl`, or the session JSONL path
   in the notify payload when available.
3. The notifier writes one Galileo trace named `codex.turn` with child spans
   for the LLM turn, tool calls, and web retrievals.
4. The notifier exits `0` even if Galileo is unavailable, and records local
   non-secret evidence in `CODEX_HOME/log/codex-galileo-notify.log`.

## Target Galileo Objects

- API base: `{config["galileo_api_base"]}`
- Project: `{config["project_name"]}` (`{config["project_id"]}`)
- Log stream: `{config["log_stream"]}` (`{config["log_stream_id"]}`)

## Direct Ingest Contract

Send completed turns to:

```text
POST /v2/projects/{{project_id}}/traces
```

Recommended request settings:

- `log_stream_id`: target Codex log stream ID
- `logging_method`: `api_direct`
- `reliable`: `true`
- `include_trace_ids`: `true`
- `session_external_id`: Codex session ID
- trace name: `codex.turn`
- trace tags: `codex`, `codex-cli`, `turn-ended`

Use `redacted_input` and `redacted_output` when sending any content. Keep
metadata-only placeholders unless the operator explicitly accepts prompt,
response, tool argument, and tool output capture.

Galileo `user_metadata` values must be strings. Convert values such as
`tool_count`, `retrieval_count`, booleans, or numeric IDs before sending.

## Verification Contract

API acceptance is not enough. Verify storage by filtering on the returned trace
ID with:

```text
POST /v2/projects/{{project_id}}/traces/count
POST /v2/projects/{{project_id}}/export_records
```

Expected evidence:

- ingest response has `records_count`, `traces_count`, `spans_count`, and
  `trace_ids`
- count response has `total_count >= 1`
- export response returns a JSONL record whose `id` equals the returned trace ID

## Guardrails

- Read the Galileo key from `GALILEO_API_KEY_FILE`; never pass it on argv.
- Redact obvious secrets, bearer tokens, JWTs, and high-entropy strings.
- Keep duplicate suppression state locally, for example
  `CODEX_HOME/log/codex-galileo-emitted-turns.json`.
- Keep the bridge fail-soft. Telemetry must not block Codex.
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
import stat
from pathlib import Path

{EMBEDDED_PRIVATE_SECRET_READER}

def _read_secret_file(env_name: str) -> str:
    path = os.environ.get(env_name, "")
    if not path:
        raise RuntimeError(f"{{env_name}} is required")
    return _read_private_secret(path, env_name)


def configure_galileo_tracing() -> None:
    os.environ.setdefault("GALILEO_PROJECT", {config["project_name"]!r})
    os.environ.setdefault("GALILEO_LOG_STREAM", {config["log_stream"]!r})
    os.environ.setdefault("GALILEO_API_BASE", {config["galileo_api_base"]!r})
    os.environ.setdefault("GALILEO_API_URL", {config["galileo_api_base"]!r})
    if {config["galileo_console_url"]!r}:
        os.environ.setdefault("GALILEO_CONSOLE_URL", {config["galileo_console_url"]!r})
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
  GALILEO_API_BASE: {json.dumps(config["galileo_api_base"])}
  GALILEO_API_URL: {json.dumps(config["galileo_api_base"])}
  GALILEO_CONSOLE_URL: {json.dumps(config["galileo_console_url"])}
""",
    )
    write_text(
        output_dir / "runtime/python-galileo-protect.py",
        f'''"""Minimal Galileo Protect invoke helper.

The API key is read from GALILEO_API_KEY_FILE at runtime. Keep payloads redacted
or minimized before invoking Protect when production data is sensitive.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any
from urllib import request

{EMBEDDED_PRIVATE_SECRET_READER}

def _read_secret_file(env_name: str) -> str:
    path = os.environ.get(env_name, "")
    if not path:
        raise RuntimeError(f"{{env_name}} is required")
    return _read_private_secret(path, env_name)


def invoke_galileo_protect(
    *,
    user_input: str,
    model_output: str = "",
    stage_name: str = "production",
    timeout: int = 300,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    api_base = os.environ.get("GALILEO_API_BASE", {config["galileo_api_base"]!r}).rstrip("/")
    body = {{
        "payload": {{"input": user_input, "output": model_output}},
        "project_id": os.environ.get("GALILEO_PROJECT_ID", {config["project_id"]!r}),
        "project_name": os.environ.get("GALILEO_PROJECT", {config["project_name"]!r}),
        "stage_name": stage_name,
        "timeout": timeout,
        "metadata": metadata or {{}},
    }}
    req = request.Request(
        f"{{api_base}}/v2/protect/invoke",
        method="POST",
        data=json.dumps(body).encode("utf-8"),
        headers={{
            "Content-Type": "application/json",
            "Galileo-API-Key": _read_secret_file("GALILEO_API_KEY_FILE"),
        }},
    )
    with request.urlopen(req, timeout=timeout + 5) as response:
        return json.loads(response.read().decode("utf-8"))
''',
    )


def render_readiness(output_dir: Path, config: dict[str, Any]) -> None:
    auth_modes = [
        {
            "mode": "api_key",
            "header": "Galileo-API-Key",
            "secret_file": config["galileo_api_key_file"],
            "status": "configured" if config["galileo_api_key_file"] else "file_path_missing",
        },
        {
            "mode": "http_basic",
            "status": "supported_by_api_but_not_rendered",
            "note": "Use a gateway or secret manager handoff; direct username/password flags are rejected.",
        },
        {
            "mode": "jwt_bearer",
            "status": "supported_by_api_but_not_rendered",
            "note": "Generate outside this skill and pass through a file-backed runtime integration.",
        },
    ]
    report = {
        "api_version": f"{SKILL_NAME}/readiness/v1",
        "galileo": {
            "api_base": config["galileo_api_base"],
            "console_url": config["galileo_console_url"],
            "healthcheck_url": config["galileo_api_base"].rstrip("/") + "/v2/healthcheck",
            "project_id": config["project_id"],
            "project_name": config["project_name"],
            "log_stream_id": config["log_stream_id"],
            "log_stream": config["log_stream"],
        },
        "auth_modes": auth_modes,
        "rbac_project_sharing_checklist": [
            "Confirm API key owner or service account can read the target project.",
            "Confirm the project is shared with the required groups.",
            "Confirm log stream, experiment, dataset, annotation, and Protect permissions are assigned.",
            "Confirm group membership mirrors production support ownership.",
        ],
        "luna_enterprise_readiness": {
            "status": "operator_check_required",
            "checks": [
                "Confirm Luna Enterprise feature availability for the tenant or deployment.",
                "Confirm metric model access, quota, and data-residency requirements.",
                "Confirm Evaluate metrics that depend on Luna are enabled for the project.",
            ],
        },
        "protect_invoke_readiness": {
            "endpoint": config["galileo_api_base"].rstrip("/") + "/v2/protect/invoke",
            "runtime_snippet": "runtime/python-galileo-protect.py",
            "status": "rendered_handoff",
        },
        "object_lifecycle_readiness": {
            "script": "scripts/apply-object-lifecycle.sh",
            "manifest": "lifecycle/object-lifecycle-manifest.example.json",
            "coverage_matrix": "lifecycle/product-coverage-matrix.json",
            "status": "rendered_apply_ready",
        },
        "signals_trends_annotations": {
            "signals": "covered_by_readiness_report",
            "trends": "covered_by_dashboard_detector_handoffs",
            "annotations_feedback": "covered_by_evaluate/annotation-feedback-handoff.md",
        },
        "latest_release": {
            "target": "2026-07-07",
            "reviewed_at": "2026-07-08",
            "asset": "readiness/galileo-2026-07-07-readiness.json",
            "features": [
                "ai_assistant_beta",
                "global_dashboards",
                "generic_alert_webhooks",
                "experiment_groups",
                "large_dataset_batched_processing",
            ],
        },
    }
    write_json(output_dir / "readiness/readiness-report.json", report)
    write_text(
        output_dir / "readiness/healthcheck.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
curl -fsS {shell_quote(config["galileo_api_base"].rstrip("/") + "/v2/healthcheck")}
echo
""",
        executable=True,
    )


def render_release_2026_07_07_assets(output_dir: Path, config: dict[str, Any]) -> None:
    release_url = "https://docs.galileo.ai/release-notes#2026-07-07"
    write_json(
        output_dir / "readiness/galileo-2026-07-07-readiness.json",
        {
            "api_version": f"{SKILL_NAME}/release-readiness/v1",
            "release_date": "2026-07-07",
            "reviewed_at": "2026-07-08",
            "source": release_url,
            "features": {
                "ai_assistant_beta": {
                    "status": "enterprise_console_enablement_handoff",
                    "automation": "no_public_api_documented",
                    "requires": [
                        "enterprise_enablement_by_galileo_support",
                        "configured_llm_integration",
                    ],
                    "grounding_inputs": [
                        "available_traces_spans_sessions_and_evaluation_scores"
                    ],
                    "safety": [
                        "read_only",
                        "verify_ai_generated_answers_against_cited_evidence",
                        "review_recommendations_before_applying_controls_or_metric_changes",
                    ],
                    "asset": "evaluate/ai-assistant-handoff.md",
                },
                "global_dashboards": {
                    "status": "organization_console_handoff",
                    "scope": "cross_project_and_log_stream",
                    "metric_families": ["safety", "evaluations", "usage", "cost"],
                    "automation": "no_global_dashboard_crud_in_public_v2_openapi",
                    "asset": "dashboards/galileo-global-dashboard-handoff.md",
                },
                "generic_alert_webhooks": {
                    "status": "console_configuration_plus_splunk_relay",
                    "payload_version": "1.0",
                    "auth_modes": ["none", "bearer_header_token", "http_basic"],
                    "downstream_correlation_fields": ["event_id", "dedup_key"],
                    "relay_delivery": "at_least_once_downstream_search_dedup",
                    "assets": [
                        "alerts/generic-webhook-handoff.md",
                        "alerts/galileo-alert-webhook-payload.example.json",
                        "scripts/galileo_alert_webhook_relay.py",
                        "splunk-platform/galileo-alert-hec-event.example.json",
                        "splunk-platform/galileo-alert-webhook-search-examples.spl",
                    ],
                },
                "experiment_groups": {
                    "status": "automated_create_or_run_assignment_plus_console_ranking_handoff",
                    "minimum_python_sdk": "galileo>=2.2.0",
                    "manifest_fields": ["experiment_group", "experiment_group_id"],
                    "precedence": ["explicit_group", "dataset_group", "other_experiments"],
                    "asset": "evaluate/experiment-groups-and-scaling-handoff.md",
                },
                "large_dataset_batched_processing": {
                    "status": "galileo_managed_batching_handoff",
                    "documented_scale": "thousands_of_rows",
                    "client_batch_size": "not_documented",
                    "requirements": [
                        "do_not_impose_legacy_low_row_caps",
                        "poll_async_job_progress",
                        "paginate_result_reads",
                        "preserve_dataset_and_experiment_group_lineage",
                    ],
                    "asset": "evaluate/experiment-groups-and-scaling-handoff.md",
                },
            },
        },
    )
    write_text(
        output_dir / "evaluate/ai-assistant-handoff.md",
        f"""# Galileo AI Assistant Beta Handoff

Source: {release_url}

The AI Assistant is an enterprise beta in the Galileo console. Ask Galileo
support to enable it, then confirm the project has a configured LLM integration
(the documented prerequisite). Review whatever relevant telemetry is available,
such as traces, spans, sessions, Signals, or evaluation scores, to assess how
well an investigation can be grounded. Open it from a Log stream or Experiment.

Treat every answer as read-only guidance. Follow its evidence links back to the
source traces or sessions and independently verify the diagnosis. Conversations
are saved, but context does not carry between conversations. The Assistant does
not apply prompt, metric, or control changes; route a reviewed recommendation to
the appropriate Evaluate workflow or Galileo Agent Observability Controls
handoff. No public AI Assistant API is documented, so this skill does not claim
automated enablement, querying, or remediation.
""",
    )
    write_text(
        output_dir / "evaluate/experiment-groups-and-scaling-handoff.md",
        f"""# Galileo Experiment Groups And Large-Dataset Scaling

Source: {release_url}

Python experiment-group support requires `galileo>=2.2.0`. Set
`experiment_group` or `experiment_group_id` on an experiment in
`lifecycle/object-lifecycle-manifest.example.json`; the lifecycle helper passes
the value to `create_experiment` and `run_experiment`. When both are set, the
SDK gives the ID precedence. Use `list_experiment_groups` and
`get_experiments(..., experiment_group=...)` to validate membership. Ranking
criteria and moving existing experiments remain reviewed console/API handoffs.
Never rename or delete system-managed groups.

If no explicit group is supplied, Galileo groups dataset-backed experiments by
dataset and places other experiments in its default group. Preserve dataset,
model, provider, prompt-version, and group lineage when comparing or exporting
results.

Galileo now batches Playground and experiment metric processing for datasets
with thousands of rows. The release does not document a client batch-size knob
or exact maximum. Do not add an artificial low row cap. Let the SDK/platform
own write batching, poll asynchronous job progress, page result reads, retain
the source dataset, and record completion/error evidence before treating a
large experiment as successful.
""",
    )
    write_text(
        output_dir / "dashboards/galileo-global-dashboard-handoff.md",
        f"""# Galileo Global Dashboard Handoff

Source: {release_url}

Use the Galileo organization-level console to build a customizable view across
projects and Log streams. Inventory safety, evaluation, usage, and cost metrics;
standardize project, Log stream, environment, owner, and service names before
charting; then verify every intended project is visible under the operator's
RBAC scope. Capture the dashboard URL, selected time range, metric definitions,
filters, and screenshot or export evidence for handoff.

The current public v2 Trends dashboard routes remain scoped to one project and
one Log stream. No documented global-dashboard CRUD route is present, so this
skill treats Galileo global dashboards as a console/evidence workflow. The
separate `dashboards/galileo-dashboard.yaml` asset builds a Splunk Observability
Cloud dashboard and must not be described as automating Galileo's global
dashboard.
""",
    )
    webhook_payload = {
        "version": "1.0",
        "event": "alert.triggered",
        "event_id": "a1b2c3d4-example",
        "timestamp": "2026-07-07T10:30:00Z",
        "alert": {
            "id": "alert-id",
            "name": "High hallucination rate",
            "status": "triggered",
            "previous_status": "healthy",
        },
        "scope": {
            "org_id": "org-id",
            "project_id": config["project_id"] or "project-id",
            "project_name": config["project_name"],
            "log_stream_id": config["log_stream_id"] or "log-stream-id",
            "log_stream_name": config["log_stream"],
        },
        "conditions": [
            {
                "metric": "metrics/context_adherence",
                "aggregation": "Average",
                "operator": "less than",
                "threshold": 0.5,
                "observed_value": 0.34,
            }
        ],
        "dedup_key": "alert-id:project-id:log-stream-id",
        "deep_link": "https://console.galileo.ai/project/example/log-streams/example",
        "metadata": {
            "team": "platform",
            "env": config["deployment_environment"],
            "service": config["service_name"],
        },
    }
    write_json(output_dir / "alerts/galileo-alert-webhook-payload.example.json", webhook_payload)
    write_json(
        output_dir / "splunk-platform/galileo-alert-hec-event.example.json",
        {
            "source": "galileo-alert-webhook",
            "sourcetype": "galileo:alert:webhook:json",
            "index": config["splunk_index"],
            "fields": {
                "galileo_alert_event_id": webhook_payload["event_id"],
                "galileo_alert_event_type": webhook_payload["event"],
                "galileo_alert_dedup_key": webhook_payload["dedup_key"],
                "galileo_alert_id": webhook_payload["alert"]["id"],
                "galileo_alert_status": webhook_payload["alert"]["status"],
                "galileo_project_id": webhook_payload["scope"]["project_id"],
                "galileo_log_stream_id": webhook_payload["scope"]["log_stream_id"],
            },
            "event": webhook_payload,
        },
    )
    write_text(
        output_dir / "alerts/generic-webhook-handoff.md",
        f"""# Galileo Generic Alert Webhook To Splunk

Source: https://docs.galileo.ai/how-to-guides/basics/set-up-alerts-on-logs#generic-webhook-notifications

Galileo configures generic webhooks in the console with no auth, a Bearer
header token, or HTTP Basic. Credentials are write-only. Splunk HEC requires
its own `Splunk` authorization scheme, so Galileo's Bearer mode cannot call HEC directly.
Deploy `scripts/galileo_alert_webhook_relay.py` behind an HTTPS reverse proxy,
configure Galileo with **Header token**, and store that distinct shared token
and the Splunk HEC token in separate mode-0600 files.
Keep the relay on loopback. If a container topology requires a non-loopback
listener, `--allow-public-http-listener` is a reviewed acknowledgement and an
operator-managed HTTPS reverse proxy remains mandatory.

```bash
python3 scripts/galileo_alert_webhook_relay.py \
  --listen-host 127.0.0.1 \
  --listen-port 8787 \
  --path /galileo/alerts \
  --galileo-webhook-token-file /run/secrets/galileo_webhook_token \
  --splunk-hec-url {config["splunk_hec_url"] or "https://splunk.example.com:8088/services/collector/event"} \
  --splunk-hec-token-file /run/secrets/splunk_hec_token \
  --splunk-index {config["splunk_index"]}
```

The relay accepts the documented payload version `1.0`, preserves the complete
event, and indexes `event_id` and `dedup_key`. Relay delivery is at-least-once:
it deliberately does not keep local deduplication state. Use the provided
Splunk search to suppress retries by `galileo_alert_event_id`, and use
`galileo_alert_dedup_key` to correlate trigger and clear lifecycle events.
Galileo does not currently document signatures or delivery retry guarantees,
so do not claim either. Send a console test event and require Galileo to show **Active**,
the relay to return HTTP 200, and Splunk to return one searchable event before
enabling production notifications. Metadata values should carry team,
environment, and service routing context without secrets.
""",
    )
    write_text(
        output_dir / "splunk-platform/galileo-alert-webhook-search-examples.spl",
        f"""index="{config["splunk_index"]}" sourcetype="galileo:alert:webhook:json"
| dedup galileo_alert_event_id
| spath path=timestamp output=galileo_alert_timestamp
| spath path=alert.name output=galileo_alert_name
| spath path=conditions{{}}.observed_value output=galileo_observed_values
| stats latest(galileo_alert_timestamp) as latest values(galileo_alert_status) as statuses values(galileo_observed_values) as observed_values by galileo_alert_dedup_key galileo_alert_id galileo_alert_name

index="{config["splunk_index"]}" sourcetype="galileo:alert:webhook:json"
| dedup galileo_alert_event_id
| spath path=timestamp output=galileo_alert_timestamp
| stats latest(galileo_alert_status) as current_status latest(galileo_alert_timestamp) as latest by galileo_alert_dedup_key galileo_project_id galileo_log_stream_id

index="{config["splunk_index"]}" sourcetype="galileo:alert:webhook:json"
| spath path=version output=galileo_payload_version
| where isnull(galileo_alert_event_id) OR isnull(galileo_alert_dedup_key) OR galileo_payload_version!="1.0"
| stats count by galileo_payload_version galileo_alert_event_type
""",
    )


def product_coverage_matrix(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Load the reviewed semantic matrix used by render and repo coverage audits."""

    del config
    matrix_path = (
        Path(__file__).resolve().parents[1]
        / "references"
        / "product-feature-matrix.json"
    )
    payload = json.loads(matrix_path.read_text(encoding="utf-8"))
    features = payload.get("features", [])
    if payload.get("schema_version") != 1 or payload.get("feature_count") != len(features):
        raise ValueError("tracked Galileo product feature matrix is invalid")
    return [
        {
            "surface": row["name"],
            "lifecycle": row["lifecycle"],
            "coverage": row["legacy_coverage"],
            "rendered_assets": row["rendered_assets"],
            "apply_script": row["apply_script"],
            "docs": row["source_url"],
        }
        for row in features
    ]


def render_object_lifecycle(output_dir: Path, config: dict[str, Any]) -> None:
    metrics = csv_values(config["metrics"])
    manifest = {
        "api_version": f"{SKILL_NAME}/object-lifecycle/v1",
        "project": {
            "name": config["project_name"],
            "id": config["project_id"],
            "create": True,
        },
        "log_stream": {
            "name": config["log_stream"],
            "id": config["log_stream_id"],
            "create": True,
            "metrics": metrics,
        },
        "datasets": [],
        "prompts": [],
        "experiments": [
            {
                "name": f"{config['project_name']}-baseline",
                "mode": "create_only",
                "experiment_group": f"{config['project_name']} Baselines",
                "experiment_group_id": "",
                "dataset_name": "",
                "prompt_name": "",
                "metrics": metrics,
                "tags": {"source": SKILL_NAME},
            }
        ],
        "experiment_processing": {
            "minimum_group_sdk": "galileo>=2.2.0",
            "large_dataset_batching": "managed_by_galileo",
            "documented_scale": "thousands_of_rows",
            "client_batch_size": "not_documented_do_not_invent",
            "validation": [
                "poll_async_job_progress",
                "page_result_reads",
                "record_completion_and_error_evidence",
            ],
        },
        "ownership_cleanup": {
            "ledger": "lifecycle/object-lifecycle-ownership.json",
            "cleanup_script": "scripts/cleanup-object-lifecycle.sh",
            "exact_id_only": True,
            "dataset_delete_requires_project_association": True,
            "project_delete_covers_child_objects": True,
            "metric_enablement": "newly_created_owned_log_stream_only",
            "existing_project_child_cleanup": {
                "dataset": "exact_id_with_project_validation",
                "prompt": "exact_id",
                "log_stream_experiment_protect_stage": "fail_closed_before_create",
            },
            "update_existing_dataset_rows": "creates_version_no_automatic_rollback",
        },
        "protect_stages": [
            {
                "name": "production",
                "project_id": config["project_id"],
                "create": False,
                "note": "Set create=true when Galileo Protect stages should be provisioned.",
            }
        ],
        "agent_control_targets": [
            {
                "target_type": "log_stream",
                "project_id": config["project_id"],
                "log_stream_id": config["log_stream_id"],
                "note": "Resolved locally; delegate control server and sink setup to galileo-agent-control-setup.",
            }
        ],
        "collaborators": {
            "projects": [],
            "datasets": [],
            "integrations": [],
            "note": "Use as an operator handoff for users, groups, and RBAC roles.",
        },
        "integrations": {
            "providers": [
                "OpenAI",
                "Anthropic",
                "AWS Bedrock",
                "AWS SageMaker",
                "Azure OpenAI",
                "Databricks",
                "Google Vertex AI",
                "Mistral",
                "NVIDIA",
                "Writer",
                "custom",
            ],
            "note": "Secrets for model/provider integrations stay outside rendered artifacts.",
        },
        "scorers": {
            "custom_code": [],
            "custom_llm": [],
            "luna": [
                {
                    "from": "completeness",
                    "to": "completeness_luna",
                    "mode": "attach_existing_slm_preset",
                },
                {
                    "from": "tool_selection_quality",
                    "to": "tool_selection_quality_luna",
                    "mode": "attach_existing_slm_preset",
                },
                {
                    "from": "tool_error_rate",
                    "to": "tool_error_rate_luna",
                    "mode": "attach_existing_slm_preset",
                },
            ],
            "preset": [],
            "note": "Use scripts/apply-luna-scorers.sh to replace OpenAI/LLM-backed preset scorer settings with available Luna/SLM preset or custom scorer IDs.",
        },
        "annotation_templates": [],
        "feedback_templates": [],
        "trends_dashboards": [],
        "trace_maintenance": {
            "query": True,
            "recompute_metrics": False,
            "delete_records": False,
            "note": "Destructive trace/session/span operations are intentionally handoff-only.",
        },
        "run_insights": {
            "health_score": "handoff",
            "token_usage": "handoff",
            "settings": "handoff",
        },
        "multimodal_observability": {
            "enabled": config["multimodal_enabled"],
            "input_modalities": csv_values(config["multimodal_input_modalities"]),
            "output_modalities": csv_values(config["multimodal_output_modalities"]),
            "capture_methods": csv_values(config["multimodal_capture_methods"]),
            "quality_metrics": csv_values(config["multimodal_quality_metrics"]),
            "splunk_asset_policy": config["multimodal_asset_policy"],
            "redaction_review_required": True,
        },
    }
    write_json(output_dir / "lifecycle/object-lifecycle-manifest.example.json", manifest)
    write_json(
        output_dir / "lifecycle/luna-scorer-map.example.json",
        {
            "api_version": f"{SKILL_NAME}/luna-scorer-map/v1",
            "strict": False,
            "list_only": config["luna_list_only"],
            "recompute": config["luna_recompute"],
            "replacements": [
                {"from": "correctness", "to": "correctness_luna"},
                {"from": "completeness", "to": "completeness_luna"},
                {"from": "instruction_adherence", "to": "instruction_adherence_luna"},
                {"from": "tool_selection_quality", "to": "tool_selection_quality_luna"},
                {"from": "tool_error_rate", "to": "tool_error_rate_luna"},
                {"from": "agent_efficiency", "to": "agent_efficiency_luna"},
            ],
            "custom_luna_scorer_ids": [
                {
                    "from": "correctness",
                    "to_id": "",
                    "scorer_type": "luna",
                    "model_type": "slm",
                    "note": "Fill to_id with a registered custom Luna scorer when no built-in correctness_luna preset exists.",
                },
                {
                    "from": "instruction_adherence",
                    "to_id": "",
                    "scorer_type": "luna",
                    "model_type": "slm",
                    "note": "Fill to_id with a registered custom Luna scorer when no built-in instruction_adherence_luna preset exists.",
                },
                {
                    "from": "agent_efficiency",
                    "to_id": "",
                    "scorer_type": "luna",
                    "model_type": "slm",
                    "note": "Fill to_id with a registered custom Luna scorer when no built-in agent_efficiency_luna preset exists.",
                },
            ],
            "notes": [
                "The apply script preserves current scorers when a requested Luna target is unavailable.",
                "Set list_only=true or pass --luna-list-only true to inventory current and available scorers without patching metric settings.",
                "Set strict=true or pass --luna-strict true when partial replacement should fail.",
                "Set remove=true on a replacement to drop a known-bad scorer when no Luna target should be enabled.",
                "Set recompute=true or pass --luna-recompute true to request metric recomputation after a successful patch.",
            ],
        },
    )
    write_json(output_dir / "lifecycle/product-coverage-matrix.json", product_coverage_matrix(config))
    write_text(
        output_dir / "lifecycle/product-coverage-matrix.md",
        "\n".join(
            [
                "# Galileo Product Coverage Matrix",
                "",
                "| Surface | Lifecycle Coverage | Apply Surface |",
                "| --- | --- | --- |",
                *[
                    "| {surface} | {coverage} | `{script}` |".format(
                        surface=item["surface"],
                        coverage=item["coverage"],
                        script=item["apply_script"],
                    )
                    for item in product_coverage_matrix(config)
                ],
                "",
                "Use `scripts/apply-object-lifecycle.sh` when the tenant needs project, "
                "log stream, dataset, prompt, experiment, metric, Protect stage, or Agent "
                "Control target creation/validation before exporting telemetry to Splunk.",
                "",
            ]
        ),
    )


def render_evaluate_assets(output_dir: Path, config: dict[str, Any]) -> None:
    multimodal_metrics = csv_values(config["multimodal_quality_metrics"])
    write_text(
        output_dir / "evaluate/evaluate-assets.yaml",
        f"""api_version: galileo-platform-setup/evaluate/v1
project:
  id: {json.dumps(config["project_id"])}
  name: {json.dumps(config["project_name"])}
log_stream:
  id: {json.dumps(config["log_stream_id"])}
  name: {json.dumps(config["log_stream"])}
experiments:
  experiment_id: {json.dumps(config["experiment_id"])}
  metrics_testing_id: {json.dumps(config["metrics_testing_id"])}
  experiment_groups: automated_for_create_and_run_with_galileo_sdk_2_2_or_later
  large_dataset_batching: galileo_managed_no_documented_client_batch_size
coverage:
  evaluate: rendered_handoff
  object_lifecycle: lifecycle/object-lifecycle-manifest.example.json
  metrics:
    agentic: operator_review
    sampling: operator_review
    filtering: operator_review
    multimodal_quality: {json.dumps(multimodal_metrics)}
  datasets: operator_review
  annotations_feedback: rendered_handoff
  signals_trends: rendered_handoff
  ai_assistant_beta: evaluate/ai-assistant-handoff.md
  experiment_groups_and_scaling: evaluate/experiment-groups-and-scaling-handoff.md
  global_dashboards: dashboards/galileo-global-dashboard-handoff.md
  generic_alert_webhooks: alerts/generic-webhook-handoff.md
  product_coverage_matrix: lifecycle/product-coverage-matrix.json
""",
    )
    write_text(
        output_dir / "evaluate/experiment-handoff.md",
        f"""# Galileo Evaluate Handoff

- Project: `{config["project_name"]}` / `{config["project_id"] or "<project-id>"}`
- Experiment ID: `{config["experiment_id"] or "<experiment-id>"}`
- Metrics testing ID: `{config["metrics_testing_id"] or "<metrics-testing-id>"}`
- Export API: `POST {config["galileo_api_base"].rstrip("/")}/v2/projects/{{project_id}}/export_records`
- Export format default: `{config["export_format"]}`
- Redaction default: `{str(config["redact"]).lower()}`

Review metric sampling, filtering, dataset lineage, and experiment comparison
coverage before enabling production dashboards or detectors. For multi-model
comparison, run the same dataset and metric set across model variants, then
track model name, provider, prompt version, and experiment group in tags or
metadata so Splunk searches can compare outputs without mixing cohorts.

For Galileo 2.2.0 and later, set `experiment_group` or
`experiment_group_id` in the lifecycle manifest. See
`evaluate/experiment-groups-and-scaling-handoff.md` for default dataset
grouping, weighted ranking, and the large-dataset batched-processing readiness workflow.
This asset is a readiness and evidence handoff; it does not itself execute a
thousand-row experiment or implement Galileo's server-managed batch polling.
""",
    )
    write_text(
        output_dir / "evaluate/annotation-feedback-handoff.md",
        """# Galileo Annotation And Feedback Handoff

Track annotation coverage, feedback completeness, fully annotated filters, and
reviewer group ownership alongside the exported Observe records. Keep free-form
feedback text redacted unless the destination Splunk index is approved for it.
""",
    )
    write_text(
        output_dir / "evaluate/multimodal-metrics-handoff.yaml",
        f"""api_version: galileo-platform-setup/multimodal-metrics/v1
project:
  id: {json.dumps(config["project_id"])}
  name: {json.dumps(config["project_name"])}
log_stream:
  id: {json.dumps(config["log_stream_id"])}
  name: {json.dumps(config["log_stream"])}
enabled: {json.dumps(config["multimodal_enabled"])}
quality_metrics:
  configured: {json.dumps(multimodal_metrics)}
  visual_quality:
    modalities: ["image", "document"]
    level: "llm_span"
    splunk_signal: "metrics.visual_quality OR metric_info.visual_quality"
  visual_fidelity:
    modalities: ["image", "document"]
    level: "llm_span"
    splunk_signal: "metrics.visual_fidelity OR metric_info.visual_fidelity"
  interruption_detection:
    modalities: ["audio"]
    level: "session"
    splunk_signal: "metrics.interruption_detection OR metric_info.interruption_detection"
validation:
  export_root_types: ["trace", "span", "session"]
  splunk_searches: "splunk-platform/multimodal-search-examples.spl"
  media_policy: {json.dumps(config["multimodal_asset_policy"])}
""",
    )


def render_multimodal_assets(output_dir: Path, config: dict[str, Any]) -> None:
    input_modalities = csv_values(config["multimodal_input_modalities"])
    output_modalities = csv_values(config["multimodal_output_modalities"])
    capture_methods = csv_values(config["multimodal_capture_methods"])
    quality_metrics = csv_values(config["multimodal_quality_metrics"])
    write_json(
        output_dir / "multimodal/multimodal-intake.example.json",
        {
            "api_version": f"{SKILL_NAME}/multimodal/v1",
            "enabled": config["multimodal_enabled"],
            "project": {
                "id": config["project_id"],
                "name": config["project_name"],
            },
            "log_stream": {
                "id": config["log_stream_id"],
                "name": config["log_stream"],
            },
            "modalities": {
                "input": input_modalities,
                "output": output_modalities,
                "supported_formats": {
                    "image": ["png", "jpeg"],
                    "audio": ["mp3", "wav"],
                    "document": ["pdf"],
                },
            },
            "capture_methods": capture_methods,
            "quality_metrics": quality_metrics,
            "splunk": {
                "asset_policy": config["multimodal_asset_policy"],
                "allow_raw_media_in_splunk": config["multimodal_allow_raw_media_in_splunk"],
                "index": config["splunk_index"],
                "sourcetype": config["splunk_sourcetype"],
                "metadata_fields": [
                    "galileo_modalities",
                    "galileo_input_modalities",
                    "galileo_output_modalities",
                    "galileo_multimodal_asset_count",
                    "multimodal_info.asset_counts",
                    "multimodal_info.metrics",
                ],
            },
            "operator_review": [
                "Confirm raw images, audio, PDFs, file names, and external URLs are approved for Galileo logging.",
                "Keep Splunk exports redacted and metadata-only unless the Splunk index is approved for raw media references.",
                "Use GalileoLogger or the LangChain/LangGraph handler for multimodal attachments; OpenTelemetry-only paths do not carry attachments.",
                "Enable multimodal metrics on the Log stream before validating Splunk searches.",
            ],
        },
    )
    write_text(
        output_dir / "multimodal/multimodal-observability.md",
        f"""# Galileo Multimodal Observability Handoff

This handoff covers Galileo multimodal logging and Splunk validation for image,
audio, and PDF/document workflows.

## Scope

- Project: `{config["project_name"]}` / `{config["project_id"] or "<project-id>"}`
- Log stream: `{config["log_stream"]}` / `{config["log_stream_id"] or "<log-stream-id>"}`
- Input modalities: `{", ".join(input_modalities) or "operator-review"}`
- Output modalities: `{", ".join(output_modalities) or "operator-review"}`
- Capture methods: `{", ".join(capture_methods) or "operator-review"}`
- Quality metrics: `{", ".join(quality_metrics) or "operator-review"}`
- Splunk media policy: `{config["multimodal_asset_policy"]}`

## Logging Paths

Use GalileoLogger when the application needs to log external media URLs or
local files. Use the LangChain or LangGraph handler when the application already
passes multimodal messages through LangChain message content. Do not rely on
OpenTelemetry-only runtime snippets for media attachments; use them for trace
context and text/tool spans, then add GalileoLogger or the LangChain handler for
actual image, audio, and document content.

## Splunk Boundary

Default Splunk export remains `redact=true` and metadata-only. The HEC bridge
extracts modality names, asset counts, MIME types, safe dimensions/duration/page
metadata, and metric names. It does not copy raw base64 content, bytes, external
media URLs, or document text into Splunk unless an operator deliberately changes
the export policy and the destination index is approved for that data.

## Metrics

- Visual Quality: image/PDF quality for task completion on LLM spans.
- Visual Fidelity: generated image/PDF compliance with visible brand or style
  requirements on LLM spans.
- Interruption Detection: turn-taking violations in audio conversations at the
  session level.

## Validation

1. Log one known image, one known PDF, and one known audio example to the target
   Log stream.
2. Confirm the Galileo trace viewer renders media inline and the configured
   multimodal metrics compute.
3. Export `trace`, `span`, and `session` records with `redact=true`.
4. Run `splunk-platform/multimodal-search-examples.spl` and confirm modality
   counts, metric fields, and trace/session IDs are present.
5. Verify searches do not contain raw base64 payloads, media URLs, or document
   text unless the operator has approved that Splunk data flow.
""",
    )
    write_text(
        output_dir / "splunk-platform/multimodal-search-examples.spl",
        f"""sourcetype="{config["splunk_sourcetype"]}" index="{config["splunk_index"]}" galileo_has_multimodal=true
| stats count sum(galileo_multimodal_asset_count) as assets by galileo_record_type galileo_modalities

sourcetype="{config["splunk_sourcetype"]}" index="{config["splunk_index"]}" galileo_has_multimodal=true
| spath path=multimodal_info.asset_counts output=asset_counts
| table _time galileo_trace_id galileo_session_id galileo_record_id galileo_input_modalities galileo_output_modalities galileo_multimodal_asset_count asset_counts

sourcetype="{config["splunk_sourcetype"]}" index="{config["splunk_index"]}" galileo_has_multimodal=true
| where isnotnull('metrics.visual_quality') OR isnotnull('metrics.visual_fidelity') OR isnotnull('metrics.interruption_detection') OR isnotnull('metric_info.visual_quality') OR isnotnull('metric_info.visual_fidelity') OR isnotnull('metric_info.interruption_detection')
| table _time galileo_trace_id galileo_session_id galileo_record_id galileo_record_type metrics metric_info multimodal_info.metrics

sourcetype="{config["splunk_sourcetype"]}" index="{config["splunk_index"]}" galileo_has_multimodal=true
| regex _raw="(?i)(data:[a-z0-9/+.-]+;base64,|\\\"base64\\\"\\s*:|https?://[^\\\" ]+\\.(png|jpe?g|pdf|mp3|wav))"
| table _time galileo_record_key galileo_trace_id galileo_record_id
""",
    )


def render_observability_controls(output_dir: Path, config: dict[str, Any]) -> None:
    """Render the Galileo console Controls surface as a platform handoff.

    Galileo does not currently publish public v2 control CRUD endpoints in the
    OpenAPI spec, so this artifact is intentionally operator/UI oriented. The
    HEC bridge still preserves control metadata when it appears on exported
    records or control spans.
    """

    write_text(
        output_dir / "controls/agent-observability-controls.md",
        f"""# Galileo Agent Observability Controls Handoff

This handoff covers the Galileo Agent Observability `Controls` console surface
for project Log streams. It is separate from this repo's standalone
`galileo-agent-control-setup` skill, which renders external/open-source Agent
Control server, SDK, and sink assets.

## Boundary

- Official public Galileo OpenAPI checked: `https://api.galileo.ai/public/v2/openapi.json`
- Documented control CRUD endpoints in public v2 OpenAPI: `not present`
- Supported here: render intake, console checklist, export validation, and
  Splunk field/search guidance
- Not claimed here: creating, attaching, cloning, deleting, or mutating
  controls through undocumented Galileo or Cisco Cloud Control APIs
- Operator intake file: `{config["controls_inventory_file"]}`
- Recommended export root type for control evidence: `{config["controls_export_root_type"]}`
- Expected inventory fields: `{config["controls_expected_fields"]}`

## Console Checklist

1. Open the target project and Log stream:
   `{config["project_name"]}` / `{config["log_stream"]}`.
2. Open the global `Controls` dashboard to review reusable control definitions.
3. For each control, record the displayed fields: control name, step, stage,
   execution environment, source, enabled state, action, selector path,
   evaluator, match threshold, and owner.
4. Attach reviewed controls to the Log stream from its `Controls` tab. Treat
   Log stream attachments as clones when the console presents them that way.
5. Generate a known-safe request and a known-match request, then inspect the
   trace or span detail view for control execution evidence.
6. Export `{config["controls_export_root_type"]}` records when you need
   control evidence in Splunk Platform. Keep `redact=true` unless raw prompt or
   response content is approved for the destination index.

## Fields To Preserve In Splunk

When Galileo export records include these values, the HEC bridge maps them into
`control_info` and top-level `galileo_control_*` fields:

- `control_name`
- `control_id`
- `stage`
- `step` or `step_type`
- `execution`
- `source`
- `action` or `decision`
- `matched`
- `confidence`
- `evaluator_name`
- `selector_path`

Missing fields mean Galileo did not include those values in the exported
record. In that case, keep the console inventory as review evidence and rely on
trace/span IDs for correlation.

## Validation Searches

Use `controls/splunk-search-examples.spl` after running `observe-export` with
`--root-type {config["controls_export_root_type"]}`.
""",
    )
    write_json(
        output_dir / "controls/control-intake.example.json",
        {
            "api_version": f"{SKILL_NAME}/observability-controls/v1",
            "project": {
                "id": config["project_id"],
                "name": config["project_name"],
            },
            "log_stream": {
                "id": config["log_stream_id"],
                "name": config["log_stream"],
            },
            "inventory_file": config["controls_inventory_file"],
            "export_root_type_for_evidence": config["controls_export_root_type"],
            "expected_fields": [
                item.strip()
                for item in str(config["controls_expected_fields"]).split(",")
                if item.strip()
            ],
            "controls": [
                {
                    "control_name": "block-prompt-injection",
                    "enabled": True,
                    "step": "LLM",
                    "stage": "Pre",
                    "execution": "Server",
                    "source": "custom",
                    "action": "deny",
                    "selector_path": "input",
                    "evaluator": {
                        "name": "configured-in-console",
                        "threshold": "operator-review",
                    },
                    "owner": "ai-platform",
                    "notes": "Inventory example only; create and attach through the Galileo console.",
                },
                {
                    "control_name": "block-output-pii",
                    "enabled": True,
                    "step": "LLM",
                    "stage": "Post",
                    "execution": "Server",
                    "source": "custom",
                    "action": "deny",
                    "selector_path": "output",
                    "evaluator": {
                        "name": "configured-in-console",
                        "threshold": "operator-review",
                    },
                    "owner": "ai-platform",
                    "notes": "Inventory example only; create and attach through the Galileo console.",
                },
                {
                    "control_name": "observe-tool-decisions",
                    "enabled": True,
                    "step": "Tool",
                    "stage": "Pre",
                    "execution": "Server",
                    "source": "custom",
                    "action": "observe",
                    "selector_path": "*",
                    "evaluator": {
                        "name": "configured-in-console",
                        "threshold": "operator-review",
                    },
                    "owner": "ai-platform",
                    "notes": "Inventory example only; create and attach through the Galileo console.",
                },
            ],
        },
    )
    write_text(
        output_dir / "controls/splunk-search-examples.spl",
        f"""sourcetype="{config["splunk_sourcetype"]}" index="{config["splunk_index"]}" galileo_control_name=*
| stats count latest(updated_at) as latest_update by galileo_control_name galileo_control_stage galileo_control_action galileo_control_matched

sourcetype="{config["splunk_sourcetype"]}" index="{config["splunk_index"]}" galileo_record_type="{config["controls_export_root_type"]}"
| where isnotnull('control_info.control_name') OR isnotnull(galileo_control_name)
| table _time galileo_trace_id galileo_record_id name galileo_control_name galileo_control_step_type galileo_control_stage galileo_control_action galileo_control_confidence galileo_control_evaluator_name

sourcetype="{config["splunk_sourcetype"]}" index="{config["splunk_index"]}" galileo_control_matched=true
| stats count by galileo_project_id galileo_log_stream_id galileo_control_name galileo_control_source
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
        output_dir / "splunk-platform/export-records-request.json",
        {
            "root_type": config["root_type"],
            "export_format": config["export_format"],
            "redact": config["redact"],
            "export_computed_metrics_only": config["export_computed_metrics_only"],
            "include_code_metric_metadata": config["include_code_metric_metadata"],
            "log_stream_id": config["log_stream_id"] or None,
            "experiment_id": config["experiment_id"] or None,
            "metrics_testing_id": config["metrics_testing_id"] or None,
            "filters": [
                item
                for item in [
                    {
                        "column_id": "updated_at",
                        "operator": "gte",
                        "type": "date",
                        "value": config["since"],
                    }
                    if config["since"]
                    else None,
                    {
                        "column_id": "updated_at",
                        "operator": "lte",
                        "type": "date",
                        "value": config["until"],
                    }
                    if config["until"]
                    else None,
                ]
                if item is not None
            ],
            "sort": {
                "column_id": "updated_at",
                "ascending": True,
                "sort_type": "column",
            },
        },
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
                "multimodal_info": {
                    "modalities": ["image", "document"],
                    "input_modalities": ["image", "document"],
                    "output_modalities": ["text"],
                    "asset_count": 2,
                    "asset_counts": {
                        "image": 1,
                        "document": 1,
                    },
                    "metrics": ["visual_quality"],
                    "assets": [
                        {
                            "field": "input",
                            "modality": "image",
                            "mime_type": "image/png",
                            "has_url": True,
                            "raw_media_omitted": True,
                        },
                        {
                            "field": "input",
                            "modality": "document",
                            "mime_type": "application/pdf",
                            "page_count": 3,
                            "raw_media_omitted": True,
                        },
                    ],
                },
                "galileo_has_multimodal": True,
                "galileo_modalities": ["image", "document"],
                "galileo_input_modalities": ["image", "document"],
                "galileo_output_modalities": ["text"],
                "galileo_multimodal_asset_count": 2,
                "control_info": {
                    "control_name": "block-output-pii",
                    "stage": "post",
                    "step_type": "llm",
                    "execution": "server",
                    "source": "custom",
                    "action": "deny",
                    "matched": True,
                    "confidence": 0.99,
                    "evaluator_name": "configured-in-console",
                    "selector_path": "output",
                },
                "galileo_control_name": "block-output-pii",
                "galileo_control_step_type": "llm",
                "galileo_control_stage": "post",
                "galileo_control_source": "custom",
                "galileo_control_action": "deny",
                "galileo_control_matched": True,
            },
        },
    )
    write_text(
        output_dir / "splunk-platform/search-examples.spl",
        f"""sourcetype="{config["splunk_sourcetype"]}" index="{config["splunk_index"]}"
| stats count by galileo_record_type status_code

sourcetype="{config["splunk_sourcetype"]}" index="{config["splunk_index"]}"
| stats latest(updated_at) as latest_update by galileo_project_id galileo_log_stream_id

sourcetype="{config["splunk_sourcetype"]}" index="{config["splunk_index"]}" galileo_has_multimodal=true
| stats count sum(galileo_multimodal_asset_count) as assets by galileo_record_type galileo_modalities
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
    traces_endpoint: {config["galileo_otel_endpoint"]}
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
        "readiness": "galileo-platform-setup",
        "object-lifecycle": "galileo-platform-setup",
        "luna-scorers": "galileo-platform-setup",
        "observe-export": "galileo-platform-setup",
        "observe-runtime": "galileo-platform-setup",
        "protect-runtime": "galileo-platform-setup",
        "evaluate-assets": "galileo-platform-setup",
        "multimodal-assets": "galileo-platform-setup",
        "observability-controls": "galileo-platform-setup",
        "splunk-hec": "splunk-hec-service-setup",
        "splunk-otlp": "splunk-connect-for-otlp-setup",
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
            "readiness": "readiness/",
            "latest_release": "readiness/galileo-2026-07-07-readiness.json",
            "lifecycle": "lifecycle/",
            "evaluate": "evaluate/",
            "alerts": "alerts/",
            "multimodal": "multimodal/",
            "controls": "controls/",
            "dashboards": "dashboards/",
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
            "galileo_saas_enterprise_readiness": {
                "status": "rendered_handoff",
                "assets": ["readiness/readiness-report.json", "readiness/healthcheck.sh"],
            },
            "galileo_object_lifecycle": {
                "status": "automated_create_or_get",
                "assets": [
                    "lifecycle/object-lifecycle-manifest.example.json",
                    "lifecycle/product-coverage-matrix.json",
                ],
                "script": "scripts/galileo_object_lifecycle.py",
                "covers": [
                    "projects",
                    "log_streams",
                    "datasets",
                    "dataset_query_preview_bulk_maintenance",
                    "prompts",
                    "prompt_rendering",
                    "experiments",
                    "experiment_metrics_and_columns",
                    "metrics",
                    "scorer_governance",
                    "protect_stages",
                    "agent_control_targets",
                    "luna_readiness",
                    "luna_studio_training_lifecycle",
                    "provider_integrations",
                    "trace_metrics_and_live_logging",
                ],
            },
            "galileo_luna_scorer_settings": {
                "status": "automated_inventory_and_metric_settings_patch",
                "script": "scripts/galileo_luna_scorers.py",
                "assets": [
                    "lifecycle/luna-scorer-map.example.json",
                    "lifecycle/luna-scorer-settings-result.json",
                ],
                "covers": [
                    "list_slm_scorers",
                    "replace_openai_llm_scorers_with_luna_slm_targets",
                    "preserve_unmapped_scorers",
                    "optional_recompute_metrics",
                    "custom_luna_scorer_id_mapping",
                ],
            },
            "galileo_full_feature_coverage_matrix": {
                "status": "rendered",
                "domain_count": len(product_coverage_matrix(config)),
                "asset": "lifecycle/product-coverage-matrix.json",
            },
            "galileo_release_2026_07_07": {
                "status": "automated_where_documented_plus_guarded_console_handoffs",
                "asset": "readiness/galileo-2026-07-07-readiness.json",
                "covers": [
                    "ai_assistant_beta_readiness",
                    "global_dashboard_console_evidence",
                    "generic_alert_webhook_v1_relay_to_splunk_hec",
                    "experiment_group_create_and_run_assignment",
                    "large_dataset_batched_processing_readiness_handoff",
                ],
            },
            "galileo_export_records_to_splunk_hec": {
                "status": "automated",
                "script": "scripts/galileo_to_splunk_hec.py",
                "delegates": ["splunk-hec-service-setup"],
            },
            "galileo_observe_opentelemetry_openinference": {
                "status": "rendered_handoff",
                "assets": ["runtime/", "otel/"],
                "delegates": [
                    "splunk-connect-for-otlp-setup",
                    "splunk-observability-otel-collector-setup",
                ],
            },
            "galileo_protect_runtime": {
                "status": "rendered_handoff",
                "assets": ["runtime/python-galileo-protect.py"],
            },
            "galileo_evaluate_experiments_datasets_annotations": {
                "status": "automated_lifecycle_plus_rendered_handoff",
                "assets": ["evaluate/", "lifecycle/", "alerts/"],
            },
            "galileo_multimodal_observability": {
                "status": "rendered_handoff",
                "assets": [
                    "multimodal/multimodal-observability.md",
                    "multimodal/multimodal-intake.example.json",
                    "evaluate/multimodal-metrics-handoff.yaml",
                    "splunk-platform/multimodal-search-examples.spl",
                ],
                "splunk_policy": config["multimodal_asset_policy"],
            },
            "galileo_agent_observability_controls": {
                "status": "rendered_handoff",
                "assets": [
                    "controls/agent-observability-controls.md",
                    "controls/control-intake.example.json",
                    "controls/splunk-search-examples.spl",
                ],
                "note": "Public Galileo v2 OpenAPI currently exposes no documented controls CRUD path; use the console and validate exported control-span evidence.",
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
        "# Galileo Platform Handoff",
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
            "## Galileo 2026-07-07 Release",
            "- AI Assistant beta: `evaluate/ai-assistant-handoff.md`",
            "- Global dashboards: `dashboards/galileo-global-dashboard-handoff.md`",
            "- Generic alert webhook relay: `alerts/generic-webhook-handoff.md`",
            "- Experiment groups and large datasets: `evaluate/experiment-groups-and-scaling-handoff.md`",
            "- Machine-readable readiness: `readiness/galileo-2026-07-07-readiness.json`",
            "",
            "## Delegation Targets",
            "- `object-lifecycle` -> `galileo-platform-setup`",
            "- `splunk-hec` -> `splunk-hec-service-setup`",
            "- `splunk-otlp` -> `splunk-connect-for-otlp-setup`",
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


def maybe_copy_runtime_scripts(output_dir: Path) -> None:
    for name in (
        "galileo_to_splunk_hec.py",
        "galileo_object_lifecycle.py",
        "galileo_luna_scorers.py",
        "galileo_alert_webhook_relay.py",
    ):
        source = Path(__file__).with_name(name)
        if not source.is_file():
            continue
        target = output_dir / "scripts" / name
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
    render_readiness(output_dir, config)
    render_release_2026_07_07_assets(output_dir, config)
    render_object_lifecycle(output_dir, config)
    render_runtime(output_dir, config)
    render_evaluate_assets(output_dir, config)
    render_multimodal_assets(output_dir, config)
    render_observability_controls(output_dir, config)
    render_splunk_platform(output_dir, config)
    render_otel(output_dir, config)
    render_o11y_specs(output_dir, config)
    scripts = render_scripts(output_dir, config, sections)
    maybe_copy_runtime_scripts(output_dir)
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
