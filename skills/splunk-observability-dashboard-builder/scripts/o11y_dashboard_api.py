#!/usr/bin/env python3
"""Splunk Observability Cloud dashboard API helper using token files only."""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


# Maximum retry attempts for transient HTTP errors (429 / 502 / 503 / 504).
# Override at test time via the O11Y_MAX_RETRIES env var.
def _max_retries() -> int:
    raw = os.environ.get("O11Y_MAX_RETRIES")
    if raw is None:
        return 4
    try:
        value = int(raw)
    except ValueError:
        return 4
    return max(1, value)


_RETRYABLE_STATUSES = {429, 502, 503, 504}


class ApiError(Exception):
    """Raised when an API call fails."""


def read_token(path: Path) -> str:
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise ApiError(f"Token file is empty: {path}")
    return token


def _retry_after_seconds(exc: HTTPError, attempt: int) -> float:
    # Honor Retry-After when present (RFC-7231 numeric seconds form).
    retry_after = exc.headers.get("Retry-After") if exc.headers else None
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except (TypeError, ValueError):
            pass
    # Exponential backoff with jitter: 1s, 2s, 4s, 8s + random 0-1s.
    return min(30.0, (2.0 ** attempt) + random.random())


def request_json(method: str, url: str, token: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    headers = {
        "X-SF-Token": token,
        "Accept": "application/json",
        "User-Agent": "splunk-observability-dashboard-builder/1 (+splunk-cisco-skills)",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)
    max_attempts = _max_retries()
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            with urlopen(request, timeout=60) as response:  # noqa: S310 - operator-supplied API URL
                text = response.read().decode("utf-8")
                return json.loads(text) if text else {}
        except HTTPError as exc:
            last_exc = exc
            # Retry on transient statuses; non-retryable errors raise immediately.
            if exc.code in _RETRYABLE_STATUSES and attempt < max_attempts - 1:
                time.sleep(_retry_after_seconds(exc, attempt))
                continue
            text = exc.read().decode("utf-8", errors="replace")
            raise ApiError(f"{method} {url} failed with HTTP {exc.code}: {text}") from exc
        except URLError as exc:
            last_exc = exc
            # Network errors get one retry pass.
            if attempt < max_attempts - 1:
                time.sleep(min(30.0, (2.0 ** attempt) + random.random()))
                continue
            raise ApiError(f"{method} {url} failed: {exc.reason}") from exc
    # Defensive: should not reach here, but surface the last error if we do.
    raise ApiError(f"{method} {url} failed after {max_attempts} attempts: {last_exc}")


def api_base(realm: str) -> str:
    if not realm:
        raise ApiError("realm is required.")
    return f"https://api.{realm}.observability.splunkcloud.com/v2"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def replace_placeholders(value: Any, group_id: str, chart_ids: dict[str, str]) -> Any:
    if isinstance(value, str):
        if value == "${dashboard_group_id}":
            return group_id
        for key, chart_id in chart_ids.items():
            if value == f"${{chart:{key}}}":
                return chart_id
        return value
    if isinstance(value, list):
        return [replace_placeholders(item, group_id, chart_ids) for item in value]
    if isinstance(value, dict):
        return {key: replace_placeholders(child, group_id, chart_ids) for key, child in value.items()}
    return value


def apply_plan(plan_dir: Path, realm: str, token_file: Path | None, dry_run: bool) -> dict[str, Any]:
    plan = load_json(plan_dir / "apply-plan.json")
    effective_realm = realm or plan.get("realm", "")
    base = api_base(effective_realm)
    if plan.get("mode") != "classic-api":
        raise ApiError("Only classic-api apply plans can be applied.")

    sequence = []
    group_info = plan["dashboard_group"]
    group_id = group_info.get("id", "")
    if group_id:
        sequence.append({"action": "use-dashboard-group", "id": group_id})
    else:
        sequence.append({"action": "create-dashboard-group", "payload_file": group_info["payload_file"]})

    for chart in plan["charts"]:
        sequence.append({"action": "create-chart", "key": chart["key"], "payload_file": chart["payload_file"]})
    sequence.append({"action": "create-dashboard", "payload_file": plan["dashboard"]["payload_file"]})

    if dry_run:
        return {"ok": True, "dry_run": True, "realm": effective_realm, "sequence": sequence}

    if token_file is None:
        raise ApiError("--token-file is required for live apply (only --dry-run can omit it).")
    token = read_token(token_file)
    if not group_id:
        group_payload = load_json(plan_dir / group_info["payload_file"])
        group_response = request_json("POST", f"{base}/dashboardgroup", token, group_payload)
        group_id = str(group_response.get("id", ""))
        if not group_id:
            raise ApiError("Dashboard group creation response did not contain id.")

    chart_ids: dict[str, str] = {}
    for chart in plan["charts"]:
        payload = load_json(plan_dir / chart["payload_file"])
        response = request_json("POST", f"{base}/chart", token, payload)
        chart_id = str(response.get("id", ""))
        if not chart_id:
            raise ApiError(f"Chart creation response for {chart['key']} did not contain id.")
        chart_ids[chart["key"]] = chart_id

    dashboard_payload = replace_placeholders(load_json(plan_dir / plan["dashboard"]["payload_file"]), group_id, chart_ids)
    dashboard_response = request_json("POST", f"{base}/dashboard", token, dashboard_payload)
    dashboard_id = str(dashboard_response.get("id", ""))
    if not dashboard_id:
        raise ApiError("Dashboard creation response did not contain id.")

    return {
        "ok": True,
        "realm": effective_realm,
        "dashboard_group_id": group_id,
        "chart_ids": chart_ids,
        "dashboard_id": dashboard_id,
    }


def normalize_metric_query(query: str) -> str:
    query = query.strip()
    if not query:
        return ""
    if ":" in query:
        return query
    if re.fullmatch(r"[A-Za-z0-9_.-]+", query):
        return f"sf_metric:*{query}*"
    return query


def discover_metrics(realm: str, token_file: Path, query: str, limit: int) -> dict[str, Any]:
    token = read_token(token_file)
    params = {"limit": str(limit)}
    normalized_query = normalize_metric_query(query)
    if normalized_query:
        params["query"] = normalized_query
    url = f"{api_base(realm)}/metric?{urlencode(params)}"
    return request_json("GET", url, token)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--plan-dir", required=True, type=Path)
    apply_parser.add_argument("--realm", default="")
    # --token-file is only required for live apply; --dry-run can omit it
    # so CI preview-only jobs do not need a real token path on disk.
    apply_parser.add_argument("--token-file", type=Path, default=None)
    apply_parser.add_argument("--dry-run", action="store_true")

    discover_parser = subparsers.add_parser("discover-metrics")
    discover_parser.add_argument("--realm", required=True)
    discover_parser.add_argument("--token-file", required=True, type=Path)
    discover_parser.add_argument("--query", default="")
    discover_parser.add_argument("--limit", type=int, default=25)

    args = parser.parse_args()
    try:
        if args.command == "apply":
            if not args.dry_run and args.token_file is None:
                parser.error("apply requires --token-file unless --dry-run is set.")
            result = apply_plan(args.plan_dir, args.realm, args.token_file, args.dry_run)
        elif args.command == "discover-metrics":
            result = discover_metrics(args.realm, args.token_file, args.query, args.limit)
        else:
            parser.error("unknown command")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, json.JSONDecodeError, ApiError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
