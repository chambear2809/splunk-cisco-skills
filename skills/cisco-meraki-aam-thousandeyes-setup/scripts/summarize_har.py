#!/usr/bin/env python3
"""Redact and summarize Meraki Dashboard HAR requests for AAM analysis."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SENSITIVE_KEY = re.compile(
    r"(authorization|cookie|set-cookie|token|secret|password|passwd|csrf|xsrf|api[-_]?key|session|saml|oauth|code)",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--har", required=True, help="Path to HAR export")
    parser.add_argument("--output-md", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--url-filter", default="", help="Case-insensitive substring filter")
    parser.add_argument("--include-get", action="store_true", help="Include GET requests")
    parser.add_argument("--max-body-chars", type=int, default=2000)
    return parser.parse_args()


def redact_value(key: str, value: Any) -> Any:
    if SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {k: redact_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(key, item) for item in value]
    if isinstance(value, str) and len(value) > 500:
        return value[:500] + "...[TRUNCATED]"
    return value


def redact_headers(headers: list[dict[str, Any]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for header in headers or []:
        name = str(header.get("name", ""))
        value = str(header.get("value", ""))
        if not name:
            continue
        result[name] = "[REDACTED]" if SENSITIVE_KEY.search(name) else value[:300]
    return result


def redact_url(url: str) -> str:
    parts = urlsplit(url)
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        query.append((key, "[REDACTED]" if SENSITIVE_KEY.search(key) else value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def parse_post_data(post_data: dict[str, Any], max_body_chars: int) -> Any:
    if not post_data:
        return None
    mime = str(post_data.get("mimeType", ""))
    text = post_data.get("text")
    params = post_data.get("params")
    if params:
        return {
            "mimeType": mime,
            "form": {str(p.get("name", "")): redact_value(str(p.get("name", "")), p.get("value", "")) for p in params},
        }
    if not isinstance(text, str):
        return {"mimeType": mime, "body": None}
    stripped = text.strip()
    if not stripped:
        return {"mimeType": mime, "body": ""}
    try:
        parsed = json.loads(stripped)
        return {"mimeType": mime, "json": redact_value("", parsed)}
    except json.JSONDecodeError:
        pass
    if "x-www-form-urlencoded" in mime:
        return {
            "mimeType": mime,
            "form": {k: redact_value(k, v) for k, v in parse_qsl(stripped, keep_blank_values=True)},
        }
    body = stripped[:max_body_chars]
    if len(stripped) > max_body_chars:
        body += "...[TRUNCATED]"
    return {"mimeType": mime, "text": body}


def json_shape(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: json_shape(child) for key, child in value.items()}
    if isinstance(value, list):
        return [json_shape(value[0])] if value else []
    if value is None:
        return "null"
    return type(value).__name__


def summarize_entry(entry: dict[str, Any], max_body_chars: int) -> dict[str, Any]:
    request = entry.get("request", {}) or {}
    response = entry.get("response", {}) or {}
    post = parse_post_data(request.get("postData", {}) or {}, max_body_chars)
    response_content = response.get("content", {}) or {}
    response_text = response_content.get("text")
    response_json_shape = None
    if isinstance(response_text, str) and response_text.strip().startswith(("{", "[")):
        try:
            response_json_shape = json_shape(json.loads(response_text))
        except json.JSONDecodeError:
            response_json_shape = None
    return {
        "startedDateTime": entry.get("startedDateTime"),
        "method": request.get("method"),
        "url": redact_url(str(request.get("url", ""))),
        "status": response.get("status"),
        "requestHeaders": redact_headers(request.get("headers", []) or []),
        "responseHeaders": redact_headers(response.get("headers", []) or []),
        "postData": post,
        "postDataShape": json_shape(post),
        "responseMimeType": response_content.get("mimeType"),
        "responseJsonShape": response_json_shape,
    }


def load_entries(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("log", {}).get("entries", [])
    if not isinstance(entries, list):
        raise SystemExit("HAR does not contain log.entries")
    return [entry for entry in entries if isinstance(entry, dict)]


def render_markdown(items: list[dict[str, Any]]) -> str:
    lines = ["# Redacted HAR Summary", ""]
    if not items:
        lines.append("No matching requests found.")
        return "\n".join(lines) + "\n"
    for idx, item in enumerate(items, start=1):
        lines.extend(
            [
                f"## {idx}. {item.get('method')} {item.get('status')}",
                "",
                f"- Time: `{item.get('startedDateTime')}`",
                f"- URL: `{item.get('url')}`",
                f"- Response MIME: `{item.get('responseMimeType')}`",
                "",
                "### Request Body Shape",
                "",
                "```json",
                json.dumps(item.get("postDataShape"), indent=2, sort_keys=True),
                "```",
                "",
            ]
        )
        post = item.get("postData")
        if post:
            lines.extend(
                [
                    "### Redacted Request Body",
                    "",
                    "```json",
                    json.dumps(post, indent=2, sort_keys=True),
                    "```",
                    "",
                ]
            )
        if item.get("responseJsonShape") is not None:
            lines.extend(
                [
                    "### Response JSON Shape",
                    "",
                    "```json",
                    json.dumps(item.get("responseJsonShape"), indent=2, sort_keys=True),
                    "```",
                    "",
                ]
            )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    entries = load_entries(Path(args.har))
    filtered: list[dict[str, Any]] = []
    allowed_methods = {"POST", "PUT", "PATCH", "DELETE"}
    if args.include_get:
        allowed_methods.add("GET")
    url_filter = args.url_filter.lower()
    for entry in entries:
        request = entry.get("request", {}) or {}
        method = str(request.get("method", "")).upper()
        url = str(request.get("url", ""))
        if method not in allowed_methods:
            continue
        if url_filter and url_filter not in url.lower():
            continue
        filtered.append(summarize_entry(entry, args.max_body_chars))

    Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output_json).write_text(json.dumps(filtered, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output_md).write_text(render_markdown(filtered), encoding="utf-8")
    print(f"Wrote {len(filtered)} summarized requests.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
