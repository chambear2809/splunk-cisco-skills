#!/usr/bin/env python3
"""List Galileo projects and Log streams using a protected API-key file."""

from __future__ import annotations

import argparse
import ipaddress
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from galileo_readback import KEY_HEADERS, NoRedirect, read_secret


MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_ROUTING_BYTES = 1024


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
        return json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
        raise RuntimeError("Galileo API returned invalid JSON") from exc


def project_items(document: Any) -> list[dict[str, Any]]:
    if not isinstance(document, dict):
        raise RuntimeError("Galileo project listing returned an invalid shape")
    values = document.get("projects")
    if not isinstance(values, list):
        raise RuntimeError("Galileo project listing has no projects array")
    if not all(isinstance(item, dict) for item in values):
        raise RuntimeError("Galileo project listing contains a malformed project")
    return values


def log_stream_items(document: Any) -> list[dict[str, Any]]:
    if isinstance(document, list):
        values = document
    elif isinstance(document, dict):
        values = document.get("log_streams")
    else:
        raise RuntimeError("Galileo Log stream listing returned an invalid shape")
    if not isinstance(values, list):
        raise RuntimeError("Galileo Log stream listing has no log_streams array")
    if not all(isinstance(item, dict) for item in values):
        raise RuntimeError("Galileo Log stream listing contains a malformed item")
    return values


def routing_text(value: Any, label: str) -> str:
    try:
        size = len(value.encode("utf-8")) if isinstance(value, str) else 0
    except UnicodeEncodeError:
        size = MAX_ROUTING_BYTES + 1
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or size > MAX_ROUTING_BYTES
        or "\\" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise RuntimeError(f"Galileo {label} must be a non-empty string")
    return value


def sanitized_log_streams(values: list[dict[str, Any]]) -> list[dict[str, str]]:
    streams: list[dict[str, str]] = []
    names_by_id: dict[str, str] = {}
    for item in values:
        stream_id = routing_text(item.get("id"), "Log stream ID")
        stream_name = routing_text(item.get("name"), "Log stream name")
        previous_name = names_by_id.get(stream_id)
        if previous_name is not None and previous_name != stream_name:
            raise RuntimeError(
                "Galileo returned conflicting names for one Log stream ID"
            )
        if previous_name is not None:
            continue
        names_by_id[stream_id] = stream_name
        streams.append({"log_stream_id": stream_id, "log_stream_name": stream_name})
    return sorted(
        streams,
        key=lambda item: (item["log_stream_name"].casefold(), item["log_stream_id"]),
    )


def list_project_log_streams(
    args: argparse.Namespace, api_key: str, project_id: str
) -> list[dict[str, str]]:
    encoded_id = urllib.parse.quote(project_id, safe="")
    values: list[dict[str, Any]] = []
    starting_token = 0
    next_token: int | None = 0
    pages = 0
    seen_tokens: set[int] = set()
    while next_token is not None and pages < args.max_pages:
        if starting_token in seen_tokens:
            raise RuntimeError("Galileo Log stream pagination repeated a token")
        seen_tokens.add(starting_token)
        query = urllib.parse.urlencode(
            {
                "include_counts": "false",
                "starting_token": starting_token,
                "limit": args.limit,
            }
        )
        endpoint = (
            f"{args.api_base.rstrip('/')}/v2/projects/{encoded_id}/"
            f"log_streams/paginated?{query}"
        )
        document = request_json(args, api_key, "GET", endpoint)
        if not isinstance(document, dict):
            raise RuntimeError("Galileo Log stream listing returned an invalid shape")
        values.extend(log_stream_items(document))
        pages += 1
        if "next_starting_token" not in document:
            raise RuntimeError(
                "Galileo Log stream listing omitted its pagination token"
            )
        raw_next = document["next_starting_token"]
        if raw_next is None:
            next_token = None
        elif type(raw_next) is int and raw_next >= 0:
            next_token = raw_next
            starting_token = raw_next
        else:
            raise RuntimeError(
                "Galileo Log stream listing returned an invalid pagination token"
            )
    if next_token is not None:
        raise RuntimeError("Galileo Log stream listing exceeded --max-pages")
    return sanitized_log_streams(values)


def matches_project(
    args: argparse.Namespace, project_id: str, project_name: str
) -> bool:
    if args.project_id and project_id != args.project_id:
        return False
    if args.project_name and project_name != args.project_name:
        return False
    return True


def discover(args: argparse.Namespace, api_key: str) -> dict[str, Any]:
    projects_by_id: dict[str, dict[str, Any]] = {}
    starting_token = 0
    next_token: int | None = 0
    pages = 0
    seen_tokens: set[int] = set()

    while next_token is not None and pages < args.max_pages:
        if starting_token in seen_tokens:
            raise RuntimeError("Galileo project pagination repeated a token")
        seen_tokens.add(starting_token)
        query = urllib.parse.urlencode(
            {
                "include_logstreams": "true",
                "starting_token": starting_token,
                "limit": args.limit,
            }
        )
        endpoint = f"{args.api_base.rstrip('/')}/v2/projects/paginated?{query}"
        payload = {
            "filters": [],
            "sort": {
                "name": "created_at",
                "ascending": False,
                "sort_type": "column",
            },
        }
        document = request_json(args, api_key, "POST", endpoint, payload)
        if not isinstance(document, dict):
            raise RuntimeError("Galileo project listing returned an invalid shape")
        for item in project_items(document):
            project_id = routing_text(item.get("id"), "project ID")
            project_name = routing_text(item.get("name"), "project name")
            if not matches_project(args, project_id, project_name):
                continue
            if "log_streams" in item:
                streams = sanitized_log_streams(
                    log_stream_items({"log_streams": item["log_streams"]})
                )
            else:
                streams = list_project_log_streams(args, api_key, project_id)
            candidate = {
                "project_id": project_id,
                "project_name": project_name,
                "log_streams": streams,
            }
            previous = projects_by_id.get(project_id)
            if previous is not None and previous != candidate:
                raise RuntimeError(
                    "Galileo returned conflicting records for one project ID"
                )
            projects_by_id[project_id] = candidate
        pages += 1
        if "next_starting_token" not in document:
            raise RuntimeError("Galileo project listing omitted its pagination token")
        raw_next = document["next_starting_token"]
        if raw_next is None:
            next_token = None
        elif type(raw_next) is int and raw_next >= 0:
            next_token = raw_next
            starting_token = raw_next
        else:
            raise RuntimeError(
                "Galileo project listing returned an invalid pagination token"
            )

    if next_token is not None:
        raise RuntimeError("Galileo project listing exceeded --max-pages")
    projects = list(projects_by_id.values())
    projects.sort(
        key=lambda item: (item["project_name"].casefold(), item["project_id"])
    )
    if (args.project_id or args.project_name) and not projects:
        raise RuntimeError("No Galileo project matched every supplied selector")
    return {
        "api_base": args.api_base.rstrip("/"),
        "project_count": len(projects),
        "projects": projects,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", required=True)
    parser.add_argument("--api-key-file", type=Path, required=True)
    parser.add_argument("--api-key-header", choices=KEY_HEADERS, required=True)
    parser.add_argument("--project-id", default="")
    parser.add_argument("--project-name", default="")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--request-timeout", type=float, default=15.0)
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
        part in {".", ".."} or any(ord(character) < 32 for character in part)
        for part in decoded_segments
    ):
        parser.error("--api-base path contains an unsafe segment")
    if parsed.params or parsed.query or parsed.fragment or "\\" in args.api_base:
        parser.error("--api-base must not contain parameters, a query, or a fragment")
    if not 1 <= args.limit <= 100:
        parser.error("--limit must be between 1 and 100")
    if not 1 <= args.max_pages <= 100:
        parser.error("--max-pages must be between 1 and 100")
    if args.request_timeout <= 0:
        parser.error("--request-timeout must be positive")
    for value, label, option in (
        (args.project_id, "project ID selector", "--project-id"),
        (args.project_name, "project name selector", "--project-name"),
    ):
        if not value:
            continue
        try:
            routing_text(value, label)
        except RuntimeError:
            parser.error(f"{option} contains unsafe content")
    return args


def main() -> None:
    args = parse_args()
    try:
        api_key = read_secret(args.api_key_file)
        result = discover(args, api_key)
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
