#!/usr/bin/env python3
"""Search Galileo for a canary without exposing credentials or trace content."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import ipaddress
import json
import os
import re
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


MAX_SECRET_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_PRIVACY_NODES = 100_000
MAX_SEARCH_PAGES = 1_000
MAX_SEARCH_RECORDS = 100_000
KEY_HEADERS = ("Galileo-API-Key", "Splunk-AO-API-Key")
CONTENT_BEARING_KEYS = {
    "arguments",
    "assistant_response",
    "completion",
    "content",
    "dataset_metadata",
    "document_content",
    "error_message",
    "exception_message",
    "exception_stacktrace",
    "files",
    "function_arguments",
    "input",
    "input_text",
    "input_value",
    "invocation_parameters",
    "llm_invocation_parameters",
    "llm_tools",
    "output",
    "output_text",
    "output_value",
    "prompt",
    "prompt_template",
    "progress_message",
    "query",
    "redacted_input",
    "redacted_output",
    "request_body",
    "response",
    "response_body",
    "result",
    "stacktrace",
    "system_prompt",
    "tags",
    "text",
    "tool_call_arguments",
    "tool_call_result",
    "tool_json_schema",
    "tool_output",
    "tool_parameters",
    "user_metadata",
    "user_prompt",
}


def valid_network_host(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        labels = host.rstrip(".").split(".")
        return (
            len(host.rstrip(".")) <= 253
            and bool(labels)
            and all(
                label
                and len(label) <= 63
                and label[0].isascii()
                and label[0].isalnum()
                and label[-1].isascii()
                and label[-1].isalnum()
                and all(
                    character.isascii() and (character.isalnum() or character == "-")
                    for character in label
                )
                for label in labels
            )
        )


def read_secret(path: Path) -> str:
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError("API-key file must be a readable regular file") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("API-key file must be a single-link regular file")
        if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
            raise ValueError("API-key file must be owned by the current user")
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError("API-key file permissions must be 0600 or stricter")
        if not 1 <= info.st_size <= MAX_SECRET_BYTES:
            raise ValueError("API-key file size is outside the allowed range")
        chunks: list[bytes] = []
        remaining = MAX_SECRET_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 8192))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        after = os.fstat(descriptor)
        if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise ValueError("API-key file changed while being read")
        if len(data) != info.st_size:
            raise ValueError("API-key file could not be read completely")
    finally:
        os.close(descriptor)
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError("API-key file must contain UTF-8 text") from exc
    if (
        len(lines) != 1
        or not lines[0]
        or any(ord(character) < 32 or ord(character) == 127 for character in lines[0])
    ):
        raise ValueError("API-key file must contain exactly one non-empty line")
    return lines[0]


def read_forbidden_content(path: Path) -> str:
    value = read_secret(path)
    if len(value) < 8:
        raise ValueError(
            "forbidden-content file must contain at least eight characters"
        )
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


def normalized(value: Any) -> str:
    return str(value or "").replace("-", "").lower()


def records_from(document: Any) -> list[dict[str, Any]]:
    if isinstance(document, list):
        values = document
    elif isinstance(document, dict):
        values = document.get("records") or document.get("data") or []
    else:
        values = []
    return [item for item in values if isinstance(item, dict)]


def reject_forbidden_content(document: Any, forbidden: tuple[str, ...]) -> None:
    if not forbidden:
        return
    pending = [document]
    visited = 0
    while pending:
        value = pending.pop()
        visited += 1
        if visited > MAX_PRIVACY_NODES:
            raise RuntimeError("Galileo privacy scan exceeded the size limit")
        if isinstance(value, str):
            if any(marker in value for marker in forbidden):
                raise RuntimeError("Galileo response contains forbidden canary content")
        elif isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, (list, tuple)):
            pending.extend(value)


def match_record(
    record: dict[str, Any], expected_trace_id: str, expected_name: str
) -> list[str]:
    matched: list[str] = []
    if expected_trace_id:
        wanted = normalized(expected_trace_id)
        if normalized(record.get("external_id")) != wanted:
            return []
        matched.append("trace_id")
    if expected_name:
        if str(record.get("name") or "") != expected_name:
            return []
        matched.append("name")
    return matched


def parse_timestamp(value: str) -> dt.datetime:
    normalized_value = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = dt.datetime.fromisoformat(normalized_value)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(dt.timezone.utc)


def request_json(
    args: argparse.Namespace,
    api_key: str,
    method: str,
    endpoint: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    data = None
    headers = {args.api_key_header: api_key}
    if payload is not None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        endpoint, data=data, headers=headers, method=method
    )
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        NoRedirect(),
    )
    try:
        with opener.open(request, timeout=args.request_timeout) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Galileo API returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("Galileo API request failed") from exc
    if len(body) > MAX_RESPONSE_BYTES:
        raise RuntimeError("Galileo API response exceeded the size limit")
    try:
        document = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
        raise RuntimeError("Galileo API returned invalid JSON") from exc
    reject_forbidden_content(document, args.forbidden_content)
    return document


def search(args: argparse.Namespace, api_key: str) -> dict[str, Any] | None:
    endpoint = f"{args.api_base.rstrip('/')}/v2/projects/{urllib.parse.quote(args.project_id, safe='')}/traces/search"
    starting_token = 0
    seen_tokens: set[int] = set()
    records_seen = 0
    for _page in range(MAX_SEARCH_PAGES):
        if starting_token in seen_tokens:
            raise RuntimeError("Galileo trace search pagination repeated a token")
        seen_tokens.add(starting_token)
        payload = {
            "starting_token": starting_token,
            "limit": args.limit,
            "log_stream_id": args.log_stream_id,
            "truncate_fields": True,
            "include_counts": True,
            "include_code_metric_metadata": False,
        }
        document = request_json(args, api_key, "POST", endpoint, payload)
        if not isinstance(document, (dict, list)):
            raise RuntimeError("Galileo trace search returned a malformed response")
        records = records_from(document)
        records_seen += len(records)
        if records_seen > MAX_SEARCH_RECORDS:
            raise RuntimeError("Galileo trace search exceeded the record limit")
        for record in records:
            matched = match_record(record, args.expected_trace_id, args.expected_name)
            try:
                created_at = parse_timestamp(str(record.get("created_at") or ""))
            except (TypeError, ValueError):
                continue
            if (
                matched
                and created_at >= args.created_after_value
                and record.get("is_complete") is True
            ):
                return {
                    "matched_by": matched,
                    "id": record.get("id"),
                    "trace_id": record.get("trace_id"),
                    "external_id": record.get("external_id"),
                    "created_at": record.get("created_at"),
                    "status_code": record.get("status_code"),
                    "num_spans": record.get("num_spans"),
                    "is_complete": record.get("is_complete"),
                }
        if not isinstance(document, dict):
            return None
        next_token = document.get("next_starting_token")
        if next_token is None:
            return None
        if (
            isinstance(next_token, bool)
            or not isinstance(next_token, int)
            or next_token < 0
        ):
            raise RuntimeError("Galileo trace search returned an invalid next token")
        starting_token = next_token
    raise RuntimeError("Galileo trace search exceeded the page limit")


def flatten_spans(values: Any) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    if not isinstance(values, list):
        return flattened
    pending = list(reversed(values))
    while pending:
        value = pending.pop()
        if not isinstance(value, dict):
            continue
        flattened.append(value)
        if len(flattened) > MAX_PRIVACY_NODES:
            raise RuntimeError("Galileo trace hierarchy exceeded the size limit")
        children = value.get("spans")
        if isinstance(children, list):
            pending.extend(reversed(children))
    return flattened


def content_state(value: Any) -> str:
    pending = [value]
    saw_redacted = False
    visited = 0
    while pending:
        item = pending.pop()
        visited += 1
        if visited > MAX_PRIVACY_NODES:
            return "present"
        if item in (None, "", [], {}):
            continue
        if isinstance(item, str):
            if item.strip().lower() in {"[redacted]", "__redacted__"}:
                saw_redacted = True
                continue
            return "present"
        if isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend(item)
        else:
            return "present"
    return "redacted" if saw_redacted else "absent"


def normalized_content_key(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value)
    return re.sub(r"[^a-zA-Z0-9]+", "_", snake).strip("_").lower()


def is_content_bearing_key(value: Any) -> bool:
    key = normalized_content_key(value)
    return key in CONTENT_BEARING_KEYS or any(
        key.endswith(f"_{suffix}")
        for suffix in (
            "arguments",
            "completion",
            "content",
            "dataset_metadata",
            "document_content",
            "error_message",
            "exception_message",
            "exception_stacktrace",
            "files",
            "function_arguments",
            "image_url",
            "input",
            "input_text",
            "input_value",
            "invocation_parameters",
            "json_schema",
            "llm_tools",
            "output",
            "output_text",
            "output_value",
            "parameters",
            "prompt",
            "progress_message",
            "result",
            "stacktrace",
            "tags",
            "text",
            "tools",
            "user_metadata",
        )
    )


def is_content_bearing_path(parts: tuple[str, ...]) -> bool:
    """Recognize sensitive leaves represented as nested or flattened paths."""

    if not parts:
        return False
    return is_content_bearing_key(".".join(parts))


def is_galileo_protection_status_path(parts: tuple[str, ...]) -> bool:
    """Identify Galileo-owned protection diagnostics, not model content."""

    normalized_parts = tuple(normalized_content_key(part) for part in parts)
    return (
        bool(normalized_parts)
        and normalized_parts[-1] == "protect_status_error_message"
    ) or (
        len(normalized_parts) >= 2
        and normalized_parts[-2:] == ("protect_status", "error_message")
    )


STRUCTURAL_CONTENT_KEYS = {
    "finish_reason",
    "id",
    "index",
    "name",
    "role",
    "tool_call_id",
    "type",
}
MESSAGE_CONTAINER_KEYS = {
    "input",
    "input_messages",
    "input_value",
    "messages",
    "output",
    "output_messages",
    "output_value",
    "redacted_input",
    "redacted_output",
}


def content_key_state(key: Any, value: Any) -> str:
    normalized_key = normalized_content_key(key)
    if normalized_key in MESSAGE_CONTAINER_KEYS or normalized_key.endswith("_messages"):
        return structured_content_state(value)
    return content_state(value)


def structured_content_state(value: Any) -> str:
    """Classify message-shaped content without treating roles as payload.

    Galileo can represent an input/output as a message object, a list of
    messages, or a JSON-encoded version of either. Structural fields such as
    ``role`` are useful hierarchy metadata, not conversation content. Unknown
    nonempty scalar fields remain fail-closed as present, and nested tool
    arguments/results are still recognized by ``is_content_bearing_key``.
    """

    if isinstance(value, str):
        direct = content_state(value)
        if direct != "present":
            return direct
        stripped = value.strip()
        if stripped.startswith(("{", "[")):
            try:
                decoded = json.loads(stripped)
            except (json.JSONDecodeError, RecursionError):
                return "present"
            if isinstance(decoded, (dict, list)):
                return structured_content_state(decoded)
        return "present"

    pending = [value]
    saw_redacted = False
    visited = 0
    while pending:
        item = pending.pop()
        visited += 1
        if visited > MAX_PRIVACY_NODES:
            return "present"
        if item in (None, "", [], {}):
            continue
        if isinstance(item, dict):
            for key, nested in item.items():
                normalized_key = normalized_content_key(key)
                if is_content_bearing_key(key):
                    state = content_key_state(key, nested)
                    if state == "present":
                        return "present"
                    if state == "redacted":
                        saw_redacted = True
                elif normalized_key in STRUCTURAL_CONTENT_KEYS:
                    continue
                elif isinstance(nested, (dict, list, tuple)):
                    pending.append(nested)
                elif nested not in (None, ""):
                    return "present"
        elif isinstance(item, (list, tuple)):
            pending.extend(item)
        else:
            state = content_state(item)
            if state == "present":
                return "present"
            if state == "redacted":
                saw_redacted = True
    return "redacted" if saw_redacted else "absent"


def recursive_content_states(value: Any) -> dict[str, int]:
    """Count privacy states for known content fields anywhere in a response."""

    counts = {"absent": 0, "redacted": 0, "present": 0}

    pending: list[tuple[Any, tuple[str, ...]]] = [(value, ())]
    visited = 0
    while pending:
        node, path = pending.pop()
        visited += 1
        if visited > MAX_PRIVACY_NODES:
            raise RuntimeError("Galileo privacy scan exceeded the size limit")
        if isinstance(node, dict):
            otlp_key = node.get("key")
            if (
                isinstance(otlp_key, str)
                and "value" in node
                and is_content_bearing_key(otlp_key)
                and not is_galileo_protection_status_path((otlp_key,))
            ):
                counts[content_key_state(otlp_key, node["value"])] += 1
            for key, item in node.items():
                next_path = (*path, str(key))
                if not is_galileo_protection_status_path(next_path) and (
                    is_content_bearing_key(key) or is_content_bearing_path(next_path)
                ):
                    counts[content_key_state(key, item)] += 1
                pending.append((item, next_path))
        elif isinstance(node, (list, tuple)):
            pending.extend((item, path) for item in node)
    return counts


def get_trace_summary(
    args: argparse.Namespace, api_key: str, record: dict[str, Any]
) -> dict[str, Any]:
    raw_galileo_id = record.get("id")
    if (
        not isinstance(raw_galileo_id, str)
        or not raw_galileo_id
        or len(raw_galileo_id) > 1024
        or "\\" in raw_galileo_id
        or any(
            ord(character) < 32 or ord(character) == 127 for character in raw_galileo_id
        )
    ):
        raise RuntimeError("Galileo search record has no trace UUID")
    galileo_id = raw_galileo_id
    endpoint = (
        f"{args.api_base.rstrip('/')}/v2/projects/"
        f"{urllib.parse.quote(args.project_id, safe='')}/traces/"
        f"{urllib.parse.quote(galileo_id, safe='')}"
    )
    detail = request_json(args, api_key, "GET", endpoint)
    if not isinstance(detail, dict) or detail.get("is_complete") is not True:
        raise RuntimeError("Galileo Get Trace returned an incomplete record")
    if not isinstance(detail.get("spans"), list):
        raise RuntimeError("Galileo Get Trace returned a malformed span hierarchy")
    spans = flatten_spans(detail.get("spans"))
    span_types = sorted(
        {str(span.get("type") or "").lower() for span in spans if span.get("type")}
    )
    missing_types = sorted(set(args.require_span_type) - set(span_types))
    if missing_types:
        raise RuntimeError(
            "Galileo trace is missing span type(s): " + ", ".join(missing_types)
        )

    records = [detail, *spans]
    states: dict[str, dict[str, int]] = {}
    for field in ("input", "output", "redacted_input", "redacted_output"):
        counts = {"absent": 0, "redacted": 0, "present": 0}
        for item in records:
            counts[structured_content_state(item.get(field))] += 1
        states[field] = counts
    if args.require_redacted_content:
        recursive_states = recursive_content_states(detail)
        if recursive_states["present"]:
            raise RuntimeError("Galileo trace contains non-redacted content")
    else:
        recursive_states = recursive_content_states({})
    raw_name = detail.get("name")
    if raw_name not in (None, "") and not isinstance(raw_name, str):
        raise RuntimeError("Galileo Get Trace returned a malformed trace name")
    name_sha256 = None
    if isinstance(raw_name, str) and raw_name:
        name_sha256 = hashlib.sha256(
            raw_name.encode("utf-8", errors="surrogatepass")
        ).hexdigest()
    return {
        "galileo_id": galileo_id,
        "name_sha256": name_sha256,
        "is_complete": True,
        "span_count": len(spans),
        "span_types": span_types,
        "content_states": states,
        "recursive_content_states": recursive_states,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--expected-origin", required=True)
    parser.add_argument("--api-key-file", type=Path, required=True)
    parser.add_argument("--api-key-header", choices=KEY_HEADERS, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--log-stream-id", required=True)
    parser.add_argument(
        "--expected-trace-id",
        default="",
        help="Source OTel trace ID, matched only against Galileo external_id",
    )
    parser.add_argument("--expected-name", default="")
    parser.add_argument("--created-after", required=True)
    parser.add_argument(
        "--require-span-type",
        action="append",
        choices=("agent", "workflow", "llm", "tool", "retriever", "control"),
        default=[],
    )
    parser.add_argument("--require-redacted-content", action="store_true")
    parser.add_argument(
        "--forbidden-content-file", action="append", default=[], type=Path
    )
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--request-timeout", type=float, default=15.0)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    try:
        args.api_base.encode("utf-8")
    except UnicodeEncodeError:
        parser.error("--api-base contains unsafe URL characters")
    if any(character.isspace() or ord(character) == 127 for character in args.api_base):
        parser.error("--api-base contains unsafe URL characters")
    parsed = urllib.parse.urlparse(args.api_base)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.netloc.endswith(":")
    ):
        parser.error("--api-base must be an HTTPS origin without credentials")
    if not valid_network_host(parsed.hostname):
        parser.error("--api-base contains an invalid hostname")
    try:
        port = parsed.port
    except ValueError:
        parser.error("--api-base contains an invalid port")
    if port is not None and not 1 <= port <= 65535:
        parser.error("--api-base contains an invalid port")
    decoded_segments = [urllib.parse.unquote(part) for part in parsed.path.split("/")]
    if any(
        part in {".", ".."} or any(ord(char) < 32 for char in part)
        for part in decoded_segments
    ):
        parser.error("--api-base path contains an unsafe segment")
    if parsed.params or parsed.query or parsed.fragment or "\\" in args.api_base:
        parser.error("--api-base must not contain parameters, a query, or a fragment")
    try:
        expected = urllib.parse.urlparse(args.expected_origin)
        expected_port = expected.port
    except ValueError:
        parser.error("--expected-origin contains an invalid port")
    if (
        expected.scheme != "https"
        or not expected.hostname
        or expected.username is not None
        or expected.password is not None
        or expected.params
        or expected.path
        or expected.query
        or expected.fragment
        or not valid_network_host(expected.hostname)
    ):
        parser.error("--expected-origin must be an exact HTTPS origin")
    expected_host = expected.hostname.lower()
    expected_url_host = f"[{expected_host}]" if ":" in expected_host else expected_host
    expected_netloc = expected_url_host + (
        f":{expected_port}"
        if expected_port is not None and expected_port != 443
        else ""
    )
    canonical_expected_origin = f"https://{expected_netloc}"
    api_port = port if port is not None else 443
    expected_effective_port = expected_port if expected_port is not None else 443
    if (
        args.expected_origin != canonical_expected_origin
        or parsed.hostname.lower() != expected_host
        or api_port != expected_effective_port
    ):
        parser.error("--api-base does not match --expected-origin")
    for value, option in (
        (args.project_id, "--project-id"),
        (args.log_stream_id, "--log-stream-id"),
        (args.expected_trace_id, "--expected-trace-id"),
        (args.expected_name, "--expected-name"),
    ):
        try:
            encoded_size = len(value.encode("utf-8"))
        except UnicodeEncodeError:
            encoded_size = 1025
        if value and (
            value != value.strip()
            or encoded_size > 1024
            or "\\" in value
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
        ):
            parser.error(f"{option} contains unsafe content")
    if not args.expected_trace_id and not args.expected_name:
        parser.error("provide --expected-trace-id and/or --expected-name")
    try:
        args.created_after_value = parse_timestamp(args.created_after)
    except (TypeError, ValueError) as exc:
        parser.error(
            f"--created-after must be an ISO-8601 timestamp with timezone: {exc}"
        )
    if not 1 <= args.limit <= 1000:
        parser.error("--limit must be between 1 and 1000")
    if args.timeout < 0 or args.poll_interval <= 0 or args.request_timeout <= 0:
        parser.error("timeouts must be positive")
    try:
        args.forbidden_content = tuple(
            read_forbidden_content(path) for path in args.forbidden_content_file
        )
    except ValueError as exc:
        parser.error(str(exc))
    return args


def main() -> None:
    args = parse_args()
    try:
        api_key = read_secret(args.api_key_file)
    except ValueError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
    deadline = time.monotonic() + args.timeout
    attempted = False
    while not attempted or time.monotonic() < deadline:
        attempted = True
        try:
            record = search(args, api_key)
        except RuntimeError as exc:
            raise SystemExit(f"ERROR: {exc}") from exc
        if record is not None:
            try:
                summary = get_trace_summary(args, api_key, record)
            except RuntimeError as exc:
                raise SystemExit(f"ERROR: {exc}") from exc
            print(
                json.dumps(
                    {
                        "status": "found",
                        "matched_by": record["matched_by"],
                        "forbidden_content_checks": len(args.forbidden_content),
                        "trace": summary,
                    },
                    sort_keys=True,
                )
            )
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SystemExit(
                "ERROR: expected Galileo trace was not found before timeout"
            )
        time.sleep(min(args.poll_interval, remaining))
    raise SystemExit("ERROR: expected Galileo trace was not found before timeout")


if __name__ == "__main__":
    main()
