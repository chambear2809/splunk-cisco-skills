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
    if args.include_raw:
        payload["input"] = record.get("input")
        payload["output"] = record.get("output")
        payload["dataset_input"] = record.get("dataset_input")
        payload["dataset_output"] = record.get("dataset_output")
    return {key: value for key, value in payload.items() if value is not None}


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
