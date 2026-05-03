#!/usr/bin/env python3
"""Apply or dry-run native Splunk Observability Cloud operations plans."""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


_RETRYABLE_STATUSES = {429, 502, 503, 504}


class ApiError(Exception):
    """Raised when an API action fails."""


def validate_action(action: dict[str, Any], index: int) -> None:
    path = str(action.get("path", ""))
    service = str(action.get("service", "o11y"))
    if service not in {"o11y", "synthetics", "on_call"}:
        raise ApiError(f"action {index} uses unsupported service {service!r}.")
    if not path.startswith("/"):
        raise ApiError(f"action {index} path must start with '/': {path}")
    if "{" in path or "}" in path:
        raise ApiError(f"action {index} path contains an unresolved placeholder: {path}")
    if path.startswith("/synthetics/tests"):
        raise ApiError(f"action {index} uses stale Synthetics path prefix; use service=synthetics and /tests/...")
    if str(action.get("object_type", "")).startswith("synthetic") and service != "synthetics":
        raise ApiError(f"action {index} synthetic action must use service=synthetics.")


def _max_retries() -> int:
    raw = os.environ.get("O11Y_MAX_RETRIES")
    if raw is None:
        return 4
    try:
        value = int(raw)
    except ValueError:
        return 4
    return max(1, value)


def read_secret_file(path: Path, label: str) -> str:
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise ApiError(f"{label} file is empty: {path}")
    return value


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ApiError(f"{path} must contain a JSON object.")
    return data


def retry_after_seconds(exc: HTTPError, attempt: int) -> float:
    retry_after = exc.headers.get("Retry-After") if exc.headers else None
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except (TypeError, ValueError):
            pass
    return min(30.0, (2.0 ** attempt) + random.random())


def request_json(
    method: str,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = None
    request_headers = {
        "Accept": "application/json",
        "User-Agent": "splunk-observability-native-ops/1 (+splunk-cisco-skills)",
        **headers,
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=request_headers, method=method)
    max_attempts = _max_retries()
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            with urlopen(request, timeout=60) as response:  # noqa: S310 - operator-rendered API URL
                text = response.read().decode("utf-8")
                return json.loads(text) if text else {}
        except HTTPError as exc:
            last_exc = exc
            if exc.code in _RETRYABLE_STATUSES and attempt < max_attempts - 1:
                time.sleep(retry_after_seconds(exc, attempt))
                continue
            text = exc.read().decode("utf-8", errors="replace")
            raise ApiError(f"{method} {url} failed with HTTP {exc.code}: {text}") from exc
        except URLError as exc:
            last_exc = exc
            if attempt < max_attempts - 1:
                time.sleep(min(30.0, (2.0 ** attempt) + random.random()))
                continue
            raise ApiError(f"{method} {url} failed: {exc.reason}") from exc
    raise ApiError(f"{method} {url} failed after {max_attempts} attempts: {last_exc}")


def o11y_api_base(realm: str) -> str:
    if not realm:
        raise ApiError("realm is required.")
    return f"https://api.{realm}.observability.splunkcloud.com/v2"


def synthetics_api_base(realm: str) -> str:
    return f"{o11y_api_base(realm)}/synthetics"


def on_call_api_base() -> str:
    return "https://api.victorops.com/api-public/v1"


def action_body(plan_dir: Path, action: dict[str, Any]) -> dict[str, Any] | None:
    payload_file = action.get("payload_file")
    if not payload_file:
        return None
    return load_json(plan_dir / str(payload_file))


def action_url(action: dict[str, Any], realm: str) -> str:
    service = action.get("service", "o11y")
    if service == "o11y":
        base = o11y_api_base(realm)
    elif service == "synthetics":
        base = synthetics_api_base(realm)
    else:
        base = on_call_api_base()
    path = str(action.get("path", ""))
    return f"{base}{path}"


def dry_run_result(plan: dict[str, Any], realm: str) -> dict[str, Any]:
    sequence = []
    for index, action in enumerate(plan.get("actions", []), start=1):
        sequence.append(
            {
                "index": index,
                "action": action.get("action"),
                "coverage": action.get("coverage"),
                "method": action.get("method"),
                "name": action.get("name"),
                "object_type": action.get("object_type"),
                "path": action.get("path"),
                "payload_file": action.get("payload_file"),
                "service": action.get("service", "o11y"),
                "url": action_url(action, realm),
                "writes": bool(action.get("writes", False)),
            }
        )
    return {"ok": True, "dry_run": True, "realm": realm, "sequence": sequence}


def apply_plan(
    plan_dir: Path,
    realm: str,
    token_file: Path | None,
    dry_run: bool,
    oncall_api_id: str,
    oncall_api_key_file: Path | None,
) -> dict[str, Any]:
    plan = load_json(plan_dir / "apply-plan.json")
    if plan.get("mode") != "native-ops":
        raise ApiError("Only native-ops apply plans can be applied.")
    for index, action in enumerate(plan.get("actions", []), start=1):
        if not isinstance(action, dict):
            raise ApiError(f"action {index} must be a JSON object.")
        validate_action(action, index)
    effective_realm = realm or str(plan.get("realm", ""))
    if dry_run:
        return dry_run_result(plan, effective_realm)
    if token_file is None:
        raise ApiError("--token-file is required for live apply.")
    o11y_token = read_secret_file(token_file, "Observability token")
    oncall_key = ""
    if any(action.get("service") == "on_call" for action in plan.get("actions", [])):
        if not oncall_api_id or oncall_api_key_file is None:
            raise ApiError("--oncall-api-id and --oncall-api-key-file are required for live On-Call API actions.")
        oncall_key = read_secret_file(oncall_api_key_file, "Splunk On-Call API key")

    responses: list[dict[str, Any]] = []
    for index, action in enumerate(plan.get("actions", []), start=1):
        service = action.get("service", "o11y")
        headers = {"X-SF-Token": o11y_token}
        if service == "on_call":
            headers = {"X-VO-Api-Id": oncall_api_id, "X-VO-Api-Key": oncall_key}
        body = action_body(plan_dir, action)
        method = str(action.get("method", "GET")).upper()
        url = action_url(action, effective_realm)
        response = request_json(method, url, headers, body)
        responses.append(
            {
                "action": action.get("action"),
                "index": index,
                "method": method,
                "name": action.get("name"),
                "object_type": action.get("object_type"),
                "response": response,
                "service": service,
                "url": url,
            }
        )
    return {"ok": True, "dry_run": False, "realm": effective_realm, "responses": responses}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    apply_parser = subparsers.add_parser("apply", help="Apply or dry-run a rendered native operations plan.")
    apply_parser.add_argument("--plan-dir", required=True, type=Path)
    apply_parser.add_argument("--realm", default="")
    apply_parser.add_argument("--token-file", type=Path)
    apply_parser.add_argument("--dry-run", action="store_true")
    apply_parser.add_argument("--oncall-api-id", default="")
    apply_parser.add_argument("--oncall-api-key-file", type=Path)

    args = parser.parse_args(argv)
    try:
        if args.command == "apply":
            result = apply_plan(
                args.plan_dir,
                args.realm,
                args.token_file,
                args.dry_run,
                args.oncall_api_id,
                args.oncall_api_key_file,
            )
        else:  # pragma: no cover - argparse prevents this.
            parser.error(f"unknown command {args.command}")
    except (OSError, ApiError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
