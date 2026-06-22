#!/usr/bin/env python3
"""Export Galileo records to Splunk HTTP Event Collector.

Secrets are accepted through file paths only. The script never prints secret
file contents.
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT_TYPES = {"session", "trace", "span"}
DIRECT_SECRET_FLAGS = {
    "--galileo-api-key",
    "--galileo-bearer-token",
    "--splunk-hec-token",
    "--hec-token",
    "--token",
    "--api-key",
    "--authorization",
    "--password",
}
MEDIA_PAYLOAD_KEYS = {
    "base64",
    "bytes",
    "content_bytes",
    "data",
    "data_uri",
    "document_text",
    "raw",
    "raw_content",
    "source",
    "text",
    "transcript",
    "url",
}
MEDIA_SAFE_KEYS = {
    "content_length",
    "duration",
    "duration_ms",
    "duration_seconds",
    "file_name",
    "file_size",
    "format",
    "height",
    "id",
    "mime_type",
    "name",
    "page_count",
    "path_hash",
    "sha256",
    "size",
    "size_bytes",
    "type",
    "width",
}
MULTIMODAL_METRIC_KEYS = {
    "interruption_detection",
    "multimodal_quality",
    "visual_fidelity",
    "visual_quality",
}


def reject_direct_secret_flags(argv: list[str]) -> None:
    for arg in argv:
        flag = arg.split("=", 1)[0] if arg.startswith("--") else arg
        if flag in DIRECT_SECRET_FLAGS:
            print(
                f"ERROR: Direct secret flag {flag} is blocked. Use --galileo-api-key-file "
                "and --splunk-hec-token-file.",
                file=sys.stderr,
            )
            raise SystemExit(2)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    reject_direct_secret_flags(raw_args)
    parser = argparse.ArgumentParser(
        description="Export Galileo records with export_records and send them to Splunk HEC."
    )
    parser.add_argument("--galileo-api-base", default=os.getenv("GALILEO_API_BASE", "https://api.galileo.ai"))
    parser.add_argument("--galileo-api-key-file", default=os.getenv("GALILEO_API_KEY_FILE", ""))
    parser.add_argument("--project-id", default=os.getenv("GALILEO_PROJECT_ID", ""))
    parser.add_argument("--log-stream-id", default=os.getenv("GALILEO_LOG_STREAM_ID", ""))
    parser.add_argument("--experiment-id", default=os.getenv("GALILEO_EXPERIMENT_ID", ""))
    parser.add_argument("--metrics-testing-id", default=os.getenv("GALILEO_METRICS_TESTING_ID", ""))
    parser.add_argument("--root-type", choices=sorted(ROOT_TYPES), default=os.getenv("GALILEO_ROOT_TYPE", "trace"))
    parser.add_argument("--export-format", choices=["jsonl", "csv"], default=os.getenv("GALILEO_EXPORT_FORMAT", "jsonl"))
    parser.add_argument("--redact", choices=["true", "false"], default=os.getenv("GALILEO_EXPORT_REDACT", "true"))
    parser.add_argument("--file-name", default=os.getenv("GALILEO_EXPORT_FILE_NAME", ""))
    parser.add_argument("--column-id", action="append", default=[], help="Column ID for CSV exports. Repeatable.")
    parser.add_argument("--since", help="UTC ISO-8601 lower bound for updated_at/created_at.")
    parser.add_argument("--until", help="UTC ISO-8601 upper bound for updated_at/created_at.")
    parser.add_argument("--time-field", default="updated_at", choices=["updated_at", "created_at"])
    parser.add_argument("--sort-field", default="updated_at")
    parser.add_argument("--filter-key", choices=["name", "column_id"], default="column_id")
    parser.add_argument("--filter-json", action="append", default=[], help="Extra Galileo filter JSON object. Repeatable.")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--max-records", type=int)
    parser.add_argument("--cursor-file", default=os.getenv("GALILEO_SPLUNK_CURSOR_FILE"))
    parser.add_argument("--splunk-hec-url", default=os.getenv("SPLUNK_HEC_URL", ""))
    parser.add_argument("--splunk-hec-token-file", default=os.getenv("SPLUNK_HEC_TOKEN_FILE", ""))
    parser.add_argument("--splunk-index", default=os.getenv("SPLUNK_INDEX"))
    parser.add_argument("--splunk-source", default=os.getenv("SPLUNK_SOURCE", "galileo"))
    parser.add_argument("--splunk-sourcetype", default=os.getenv("SPLUNK_SOURCETYPE", "galileo:observe:json"))
    parser.add_argument("--splunk-host", default=os.getenv("SPLUNK_HOST"))
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--indexed-fields", action="store_true", help="Add flat indexed fields to the HEC envelope.")
    parser.add_argument("--include-raw", action="store_true", help="Include raw input/output fields. Use only after approval.")
    parser.add_argument("--print-export-request", action="store_true", help="Print the export_records request JSON and exit.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--insecure", action="store_true", help="Disable TLS verification for Splunk HEC.")
    args = parser.parse_args(raw_args)
    if not args.project_id:
        raise SystemExit("ERROR: --project-id or GALILEO_PROJECT_ID is required.")
    return args


def read_secret_file(path: str, label: str) -> str:
    if not path:
        raise SystemExit(f"ERROR: {label} file path is required.")
    secret_path = Path(path).expanduser()
    if not secret_path.is_file():
        raise SystemExit(f"ERROR: {label} file is missing: {secret_path}")
    value = secret_path.read_text(encoding="utf-8").strip()
    if not value:
        raise SystemExit(f"ERROR: {label} file is empty: {secret_path}")
    return value


def iso_to_epoch(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    text = value
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def normalize_iso(value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError("empty timestamp")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def load_cursor(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    cursor_path = Path(path)
    if not cursor_path.exists():
        return {}
    with cursor_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_cursor(path: str | None, payload: dict[str, Any]) -> None:
    if not path:
        return
    cursor_path = Path(path)
    cursor_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cursor_path.with_suffix(cursor_path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    tmp_path.replace(cursor_path)


def request_bytes(
    method: str,
    url: str,
    headers: dict[str, str],
    body: Any | None = None,
    ssl_context: ssl.SSLContext | None = None,
) -> tuple[bytes, str]:
    data = None
    if body is not None:
        data = json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers = {**headers, "Content-Type": "application/json"}
    request = urllib.request.Request(url, method=method, headers=headers, data=data)
    try:
        with urllib.request.urlopen(request, context=ssl_context, timeout=60) as response:
            return response.read(), response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{method} {url} failed: {exc.reason}") from exc


def request_json(
    method: str,
    url: str,
    headers: dict[str, str],
    body: Any | None = None,
    ssl_context: ssl.SSLContext | None = None,
) -> Any:
    raw, _content_type = request_bytes(method, url, headers, body, ssl_context)
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def galileo_headers(args: argparse.Namespace) -> dict[str, str]:
    api_key = read_secret_file(args.galileo_api_key_file, "Galileo API key")
    return {"Galileo-API-Key": api_key}


def splunk_headers(args: argparse.Namespace) -> dict[str, str]:
    hec_token = read_secret_file(args.splunk_hec_token_file, "Splunk HEC token")
    return {
        "Authorization": f"Splunk {hec_token}",
        "Content-Type": "application/json",
    }


def normalize_hec_url(raw_url: str | None) -> str:
    if not raw_url:
        raise SystemExit("ERROR: --splunk-hec-url or SPLUNK_HEC_URL is required.")
    url = raw_url.rstrip("/")
    parsed = urllib.parse.urlparse(url)
    if "/services/collector" in parsed.path:
        return url
    return f"{url}/services/collector/event"


def build_filters(args: argparse.Namespace, since: str | None) -> list[dict[str, Any]]:
    filters: list[dict[str, Any]] = []
    if since:
        filters.append(
            {
                args.filter_key: args.time_field,
                "operator": "gte",
                "type": "date",
                "value": normalize_iso(since),
            }
        )
    if args.until:
        filters.append(
            {
                args.filter_key: args.time_field,
                "operator": "lte",
                "type": "date",
                "value": normalize_iso(args.until),
            }
        )
    for raw_filter in args.filter_json:
        try:
            parsed = json.loads(raw_filter)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Invalid --filter-json: {exc}") from exc
        if not isinstance(parsed, dict):
            raise SystemExit("--filter-json must be a JSON object.")
        filters.append(parsed)
    return filters


def build_export_records_request(args: argparse.Namespace, since: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "root_type": args.root_type,
        "export_format": args.export_format,
        "redact": str(args.redact).lower() not in {"0", "false", "no"},
        "filters": build_filters(args, since),
        "sort": {
            "column_id": args.sort_field,
            "ascending": True,
            "sort_type": "column",
        },
    }
    if args.column_id:
        body["column_ids"] = args.column_id
    if args.file_name:
        body["file_name"] = args.file_name
    if args.log_stream_id:
        body["log_stream_id"] = args.log_stream_id
    if args.experiment_id:
        body["experiment_id"] = args.experiment_id
    if args.metrics_testing_id:
        body["metrics_testing_id"] = args.metrics_testing_id
    return body


def parse_jsonl(text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def extract_records_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("records", "data", "items", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    for key in ("jsonl", "content", "file_content"):
        value = payload.get(key)
        if isinstance(value, str):
            return parse_jsonl(value)
    return [payload]


def download_records_from_url(url: str, headers: dict[str, str]) -> list[dict[str, Any]]:
    raw, _content_type = request_bytes("GET", url, headers)
    text = raw.decode("utf-8")
    try:
        return extract_records_from_payload(json.loads(text))
    except json.JSONDecodeError:
        return parse_jsonl(text)


def nested_lookup(node: dict[str, Any], path: str) -> Any:
    current: Any = node
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def nested_sources(record: dict[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = [record]
    for key in (
        "control_info",
        "control",
        "agent_control",
        "attributes",
        "span_attributes",
        "metadata",
        "user_metadata",
        "metrics",
        "metric_info",
    ):
        value = record.get(key)
        if isinstance(value, dict):
            sources.append(value)
            for nested_key in ("control_info", "control", "agent_control", "evaluator", "condition"):
                nested = value.get(nested_key)
                if isinstance(nested, dict):
                    sources.append(nested)
    return sources


def first_present(sources: list[dict[str, Any]], aliases: tuple[str, ...]) -> Any:
    for alias in aliases:
        for source in sources:
            value = source.get(alias)
            if value in (None, "") and "." in alias:
                value = nested_lookup(source, alias)
            if value not in (None, ""):
                return value
    return None


def record_has_control_hints(record: dict[str, Any]) -> bool:
    for key in ("control_info", "control", "agent_control", "control_name", "control_id"):
        if key in record:
            return True
    for source in nested_sources(record):
        for key in source:
            normalized = str(key).lower().replace("-", "_").replace(".", "_")
            if normalized.startswith("control_") or normalized in {
                "evaluator_name",
                "execution_environment",
                "selector_path",
            }:
                return True
    for key in ("type", "span_type", "kind"):
        value = str(record.get(key, "")).lower()
        if "control" in value:
            return True
    return False


def record_is_control_span(record: dict[str, Any]) -> bool:
    for key in ("type", "span_type", "kind"):
        if "control" in str(record.get(key, "")).lower():
            return True
    return False


def extract_control_info(record: dict[str, Any]) -> dict[str, Any]:
    if not record_has_control_hints(record):
        return {}

    sources = nested_sources(record)
    aliases: dict[str, tuple[str, ...]] = {
        "control_id": ("control_id", "control.id", "control_info.control_id", "agent_control.control_id"),
        "stage": (
            "control_stage",
            "control.stage",
            "control_info.stage",
            "agent_control.stage",
            "check_stage",
            "scope.stage",
            "scope.stages",
            "stage",
        ),
        "step_type": (
            "control_step",
            "control_step_type",
            "control.step",
            "control.step_type",
            "control_info.step",
            "control_info.step_type",
            "agent_control.step",
            "agent_control.step_type",
            "step",
            "step_type",
            "step.type",
            "scope.step",
            "scope.steps",
            "scope.step_type",
            "scope.step_types",
        ),
        "execution": (
            "control_execution",
            "control.execution",
            "control_info.execution",
            "agent_control.execution",
            "execution_environment",
            "execution",
        ),
        "action": (
            "control_action",
            "control.action.decision",
            "control.action",
            "control_info.action.decision",
            "control_info.action",
            "agent_control.action",
            "action.decision",
            "action",
            "decision",
        ),
        "matched": (
            "control_matched",
            "control.matched",
            "control_info.matched",
            "agent_control.matched",
            "result.matched",
            "matched",
            "match",
            "is_match",
        ),
        "confidence": (
            "control_confidence",
            "control.confidence",
            "control_info.confidence",
            "agent_control.confidence",
            "result.confidence",
            "confidence_score",
            "confidence",
            "score",
        ),
        "evaluator_name": (
            "evaluator_name",
            "control.evaluator.name",
            "control_info.evaluator.name",
            "control_info.evaluator_name",
            "agent_control.evaluator_name",
            "evaluator.name",
            "condition.evaluator.name",
            "control_evaluator_name",
        ),
        "selector_path": (
            "selector_path",
            "control.selector.path",
            "control_info.selector.path",
            "control_info.selector_path",
            "agent_control.selector_path",
            "selector.path",
            "condition.selector.path",
            "control_selector_path",
        ),
        "source": (
            "control_source",
            "control.source",
            "control_info.source",
            "agent_control.source",
        ),
    }
    info = {
        key: value
        for key, value in ((name, first_present(sources, field_aliases)) for name, field_aliases in aliases.items())
        if value not in (None, "")
    }
    control_name = first_present(
        sources,
        (
            "control_name",
            "control.name",
            "control_info.control_name",
            "control_info.name",
            "agent_control.control_name",
        ),
    )
    if control_name in (None, "") and record_is_control_span(record):
        control_name = first_present([record], ("name", "span_name"))
    if control_name not in (None, ""):
        info["control_name"] = control_name
    return info


def normalize_modality(value: Any) -> str | None:
    text = str(value or "").strip().lower().replace("-", "_")
    if not text:
        return None
    if text in {"image", "images", "input_image", "image_url"}:
        return "image"
    if text in {"audio", "voice", "input_audio", "audio_url"}:
        return "audio"
    if text in {"document", "documents", "pdf", "pdfs", "document_url", "file", "files"}:
        return "document"
    if text in {"text", "message"}:
        return "text"
    if text.startswith("image/"):
        return "image"
    if text.startswith("audio/"):
        return "audio"
    if text in {"application/pdf", "application/x_pdf"}:
        return "document"
    return None


def modality_from_mapping(node: dict[str, Any], hint: str | None = None) -> str | None:
    for key in ("modality", "media_type", "asset_type", "content_type", "mime_type", "type"):
        modality = normalize_modality(node.get(key))
        if modality:
            return modality
    for key in ("image_url", "input_image", "audio_url", "input_audio", "document_url", "pdf"):
        if key in node:
            return normalize_modality(key)
    return hint


def safe_media_item(node: dict[str, Any], *, field: str, modality: str) -> dict[str, Any]:
    item: dict[str, Any] = {
        "field": field,
        "modality": modality,
        "raw_media_omitted": True,
    }
    for key in MEDIA_SAFE_KEYS:
        value = node.get(key)
        if isinstance(value, (str, int, float, bool)) and value not in ("", None):
            item[key] = value
    for key in ("url", "source", "path", "file_path", "base64", "bytes", "data", "data_uri", "raw", "content"):
        if key in node and node.get(key) not in (None, ""):
            item[f"has_{key}"] = True
    for nested_key in ("image_url", "audio_url", "document_url"):
        nested = node.get(nested_key)
        if isinstance(nested, dict):
            for key in MEDIA_SAFE_KEYS:
                value = nested.get(key)
                if isinstance(value, (str, int, float, bool)) and value not in ("", None):
                    item.setdefault(key, value)
            if nested.get("url"):
                item["has_url"] = True
    return item


def collect_media_items(node: Any, *, field: str, hint: str | None = None) -> list[dict[str, Any]]:
    if isinstance(node, list):
        items: list[dict[str, Any]] = []
        for child in node:
            items.extend(collect_media_items(child, field=field, hint=hint))
        return items
    if not isinstance(node, dict):
        return []

    modality = modality_from_mapping(node, hint)
    if modality and modality != "text":
        return [safe_media_item(node, field=field, modality=modality)]

    items = []
    for key, value in node.items():
        normalized_key = str(key).lower().replace("-", "_")
        if normalized_key in MEDIA_PAYLOAD_KEYS and not isinstance(value, (dict, list)):
            continue
        child_hint = normalize_modality(normalized_key)
        items.extend(collect_media_items(value, field=field, hint=child_hint or hint))
    return items


def add_modalities_from_value(target: set[str], value: Any) -> None:
    if isinstance(value, str):
        for part in value.replace(";", ",").split(","):
            modality = normalize_modality(part)
            if modality and modality != "text":
                target.add(modality)
        return
    if isinstance(value, list):
        for item in value:
            add_modalities_from_value(target, item)
        return
    if isinstance(value, dict):
        modality = modality_from_mapping(value)
        if modality and modality != "text":
            target.add(modality)


def multimodal_metric_names(record: dict[str, Any]) -> list[str]:
    found: set[str] = set()
    for parent_key in ("metrics", "metric_info"):
        value = record.get(parent_key)
        if not isinstance(value, dict):
            continue
        for key, metric_value in value.items():
            normalized = str(key).lower().replace("-", "_").replace(" ", "_")
            if normalized in MULTIMODAL_METRIC_KEYS and metric_value not in (None, ""):
                found.add(normalized)
    return sorted(found)


def extract_multimodal_info(record: dict[str, Any]) -> dict[str, Any]:
    input_items: list[dict[str, Any]] = []
    output_items: list[dict[str, Any]] = []
    other_items: list[dict[str, Any]] = []
    for field in ("input", "dataset_input"):
        input_items.extend(collect_media_items(record.get(field), field=field))
    for field in ("output", "dataset_output"):
        output_items.extend(collect_media_items(record.get(field), field=field))
    for field in ("messages", "attachments", "files", "media", "content_blocks"):
        other_items.extend(collect_media_items(record.get(field), field=field))

    input_modalities = {item["modality"] for item in input_items}
    output_modalities = {item["modality"] for item in output_items}
    modalities = set(input_modalities) | set(output_modalities) | {item["modality"] for item in other_items}

    add_modalities_from_value(input_modalities, record.get("input_modalities"))
    add_modalities_from_value(output_modalities, record.get("output_modalities"))
    for key in ("modalities", "input_modalities", "output_modalities", "modality", "media_type", "mime_type"):
        add_modalities_from_value(modalities, record.get(key))
    for source_key in ("metadata", "user_metadata", "attributes", "span_attributes"):
        source = record.get(source_key)
        if isinstance(source, dict):
            add_modalities_from_value(input_modalities, source.get("input_modalities"))
            add_modalities_from_value(output_modalities, source.get("output_modalities"))
            for key in (
                "modalities",
                "input_modalities",
                "output_modalities",
                "modality",
                "media_type",
                "mime_type",
            ):
                add_modalities_from_value(modalities, source.get(key))

    assets = input_items + output_items + other_items
    metric_names = multimodal_metric_names(record)
    if not assets and not modalities and not metric_names:
        return {}

    asset_counts = {name: 0 for name in sorted(modalities)}
    for item in assets:
        asset_counts[item["modality"]] = asset_counts.get(item["modality"], 0) + 1
    for name in list(asset_counts):
        if asset_counts[name] == 0 and name not in modalities:
            del asset_counts[name]

    return {
        "modalities": sorted(modalities),
        "input_modalities": sorted(input_modalities),
        "output_modalities": sorted(output_modalities),
        "asset_count": len(assets),
        "asset_counts": asset_counts,
        "metrics": metric_names,
        "assets": assets[:50],
        "raw_media_policy": "omitted_by_default",
    }


def query_galileo(args: argparse.Namespace, since: str | None) -> list[dict[str, Any]]:
    url = f"{args.galileo_api_base.rstrip('/')}/v2/projects/{args.project_id}/export_records"
    headers = galileo_headers(args)
    raw, content_type = request_bytes("POST", url, headers, build_export_records_request(args, since))
    text = raw.decode("utf-8")
    if "jsonl" in content_type.lower() or (
        args.export_format == "jsonl" and "\n" in text and not text.lstrip().startswith(("{", "["))
    ):
        records = parse_jsonl(text)
    else:
        payload = json.loads(text) if text else {}
        for key in ("file_url", "download_url", "url"):
            value = payload.get(key) if isinstance(payload, dict) else None
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                records = download_records_from_url(value, headers)
                break
        else:
            records = extract_records_from_payload(payload)
    if args.max_records:
        return records[: args.max_records]
    return records


def compact_record(record: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    record_id = record.get("id")
    run_id = record.get("run_id") or args.log_stream_id
    record_type = record.get("type") or args.root_type
    payload: dict[str, Any] = {
        "galileo_record_key": f"{record.get('project_id') or args.project_id}:{run_id}:{record_type}:{record_id}",
        "galileo_project_id": record.get("project_id") or args.project_id,
        "galileo_log_stream_id": run_id,
        "galileo_record_id": record_id,
        "galileo_record_type": record_type,
        "galileo_trace_id": record.get("trace_id"),
        "galileo_session_id": record.get("session_id"),
        "galileo_parent_id": record.get("parent_id"),
        "external_id": record.get("external_id"),
        "name": record.get("name"),
        "status_code": record.get("status_code"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "is_complete": record.get("is_complete"),
        "tags": record.get("tags") or [],
        "user_metadata": record.get("user_metadata") or {},
        "dataset_metadata": record.get("dataset_metadata") or {},
        "metrics": record.get("metrics") or {},
        "metric_info": record.get("metric_info") or {},
        "feedback_rating_info": record.get("feedback_rating_info") or {},
        "annotations": record.get("annotations") or {},
        "redacted_input": record.get("redacted_input"),
        "redacted_output": record.get("redacted_output"),
    }
    control_info = extract_control_info(record)
    if control_info:
        payload["control_info"] = control_info
        for key, value in control_info.items():
            if isinstance(value, (str, int, float, bool)):
                field_key = key.removeprefix("control_")
                payload[f"galileo_control_{field_key}"] = value
    multimodal_info = extract_multimodal_info(record)
    if multimodal_info:
        payload["multimodal_info"] = multimodal_info
        payload["galileo_has_multimodal"] = True
        payload["galileo_modalities"] = multimodal_info.get("modalities", [])
        payload["galileo_input_modalities"] = multimodal_info.get("input_modalities", [])
        payload["galileo_output_modalities"] = multimodal_info.get("output_modalities", [])
        payload["galileo_multimodal_asset_count"] = multimodal_info.get("asset_count", 0)
        if multimodal_info.get("metrics"):
            payload["galileo_multimodal_metrics"] = multimodal_info["metrics"]
    if args.include_raw:
        payload["input"] = record.get("input")
        payload["output"] = record.get("output")
        payload["dataset_input"] = record.get("dataset_input")
        payload["dataset_output"] = record.get("dataset_output")
    return {key: value for key, value in payload.items() if value is not None}


def hec_indexed_field_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def hec_envelope(record: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    event = compact_record(record, args)
    timestamp = iso_to_epoch(record.get(args.time_field)) or iso_to_epoch(record.get("created_at")) or time.time()
    envelope: dict[str, Any] = {
        "time": timestamp,
        "source": args.splunk_source,
        "sourcetype": args.splunk_sourcetype,
        "event": event,
    }
    if args.splunk_index:
        envelope["index"] = args.splunk_index
    if args.splunk_host:
        envelope["host"] = args.splunk_host
    if args.indexed_fields:
        envelope["fields"] = {
            "galileo_project_id": str(event.get("galileo_project_id", "")),
            "galileo_log_stream_id": str(event.get("galileo_log_stream_id", "")),
            "galileo_record_type": str(event.get("galileo_record_type", "")),
            "galileo_record_id": str(event.get("galileo_record_id", "")),
            "galileo_trace_id": str(event.get("galileo_trace_id", "")),
            "galileo_session_id": str(event.get("galileo_session_id", "")),
            "galileo_record_key": str(event.get("galileo_record_key", "")),
        }
        for key in (
            "galileo_control_name",
            "galileo_control_stage",
            "galileo_control_action",
            "galileo_control_matched",
            "galileo_has_multimodal",
            "galileo_multimodal_asset_count",
        ):
            if key in event:
                envelope["fields"][key] = hec_indexed_field_value(event.get(key, ""))
        for key in ("galileo_modalities", "galileo_input_modalities", "galileo_output_modalities"):
            value = event.get(key)
            if isinstance(value, list):
                envelope["fields"][key] = ",".join(str(item) for item in value)
    return envelope


def send_to_splunk(args: argparse.Namespace, envelopes: list[dict[str, Any]]) -> None:
    if not envelopes:
        return
    url = normalize_hec_url(args.splunk_hec_url)
    context = ssl._create_unverified_context() if args.insecure else None
    response = request_json("POST", url, splunk_headers(args), envelopes, context)
    if isinstance(response, dict) and response.get("code") not in (None, 0):
        raise RuntimeError(f"Splunk HEC rejected batch: {response}")


def chunks(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def max_timestamp(records: list[dict[str, Any]], field: str) -> str | None:
    values = [value for value in (record.get(field) for record in records) if isinstance(value, str)]
    if not values:
        return None
    return max(normalize_iso(value) for value in values)


def main() -> int:
    args = parse_args()
    cursor = load_cursor(args.cursor_file)
    since = args.since or cursor.get(args.time_field)
    if args.print_export_request:
        print(json.dumps(build_export_records_request(args, since), indent=2, sort_keys=True))
        return 0
    records = query_galileo(args, since)
    envelopes = [hec_envelope(record, args) for record in records]

    print(f"Fetched {len(records)} Galileo {args.root_type} record(s).", file=sys.stderr)
    if envelopes:
        print("First Splunk envelope sample:", file=sys.stderr)
        print(json.dumps(envelopes[0], indent=2, sort_keys=True), file=sys.stderr)

    if args.dry_run:
        print("Dry run complete; no events sent.", file=sys.stderr)
        return 0

    for batch in chunks(envelopes, args.batch_size):
        send_to_splunk(args, batch)

    cursor_value = max_timestamp(records, args.time_field)
    if cursor_value:
        write_cursor(
            args.cursor_file,
            {
                args.time_field: cursor_value,
                "project_id": args.project_id,
                "log_stream_id": args.log_stream_id,
                "root_type": args.root_type,
                "updated_by": "galileo_to_splunk_hec.py",
            },
        )
    print(f"Sent {len(envelopes)} event(s) to Splunk HEC.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
