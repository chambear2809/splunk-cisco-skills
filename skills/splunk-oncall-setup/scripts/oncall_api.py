#!/usr/bin/env python3
"""Apply or dry-run a rendered Splunk On-Call apply plan.

Reads ``apply-plan.json`` plus per-action JSON payloads under ``payloads/``
and posts them to the Splunk On-Call public API (host
``https://api.victorops.com``) with ``X-VO-Api-Id`` + ``X-VO-Api-Key`` header
auth read from a chmod-600 file. Per-endpoint token-bucket governors honor
the documented limits (default 2/sec, user-batch 1/sec, reporting v2
incidents 1/min). All output is structured and **no secret material is
ever logged**.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import stat
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


_RETRYABLE_STATUSES = {429, 502, 503, 504}
_DEFAULT_API_BASE = "https://api.victorops.com"
_DEFAULT_USER_AGENT = "splunk-oncall-setup/1 (+splunk-cisco-skills)"

# Rates from references/rate-limits.md, verified against the public API spec.
RATE_BUCKETS = {
    # Default for nearly every endpoint.
    "default": {"per_period": 2.0, "period_seconds": 1.0},
    # POST /v1/user/batch and GET /v1/profile/{username}/policies (V1 read).
    "user_batch_or_personal_paging_v1_read": {"per_period": 1.0, "period_seconds": 1.0},
    # /v1/alertRules.
    "alert_rules": {"per_period": 2.0, "period_seconds": 1.0},
    # /api-reporting/v2/incidents.
    "reporting_v2_incidents": {"per_period": 1.0, "period_seconds": 60.0},
}


class ApiError(Exception):
    """Raised when an apply step fails or the plan is invalid."""


def _max_retries() -> int:
    raw = os.environ.get("ONCALL_MAX_RETRIES")
    if raw is None:
        return 4
    try:
        value = int(raw)
    except ValueError:
        return 4
    return max(1, value)


def read_secret_file(path: Path, label: str) -> str:
    if not path.is_file():
        raise ApiError(f"{label} file does not exist: {path}")
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as exc:
        raise ApiError(f"Cannot stat {label} file {path}: {exc}") from exc
    if mode & 0o077:
        raise ApiError(
            f"{label} file {path} has overly permissive mode {oct(mode)}; require 0600 (group/world bits cleared)."
        )
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise ApiError(f"{label} file is empty: {path}")
    return value


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ApiError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ApiError(f"{path} must contain a JSON object.")
    return data


def safe_plan_path(plan_dir: Path, relative: str) -> Path:
    """Resolve a plan-relative payload path; refuse to escape plan_dir."""
    if not isinstance(relative, str) or not relative:
        raise ApiError(f"plan payload file must be a non-empty string (got {relative!r})")
    plan_root = plan_dir.resolve()
    candidate = (plan_root / relative).resolve()
    try:
        candidate.relative_to(plan_root)
    except ValueError as exc:
        raise ApiError(
            f"plan payload file {relative!r} escapes plan directory {plan_root}"
        ) from exc
    return candidate


def validate_action(action: dict[str, Any], index: int) -> None:
    """Validate a single rendered action before we issue an HTTP request.

    Refuses any action that:
      - uses a service other than ``on_call`` (the renderer is the
        canonical home for Splunk On-Call API actions)
      - does not start with ``/`` (would otherwise turn into a relative URL)
      - contains an unresolved ``{...}`` or ``<...>`` placeholder (which
        would otherwise become a literal segment in the URL)
      - contains CR/LF, NUL, or whitespace characters in the path (header
        smuggling guard)
      - uses an HTTP method outside the documented Splunk On-Call set.
    """
    path = str(action.get("path", ""))
    service = str(action.get("service", "on_call"))
    if service != "on_call":
        raise ApiError(f"action {index} uses unsupported service {service!r}.")
    if not path.startswith("/"):
        raise ApiError(f"action {index} path must start with '/': {path}")
    if "{" in path or "}" in path or "<" in path or ">" in path:
        raise ApiError(f"action {index} path contains an unresolved placeholder: {path}")
    if any(ch in path for ch in ("\n", "\r", "\x00")):
        raise ApiError(f"action {index} path contains forbidden control characters.")
    method = str(action.get("method", "")).upper()
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        raise ApiError(f"action {index} has unsupported method {method!r}.")


def retry_after_seconds(exc: HTTPError, attempt: int) -> float:
    retry_after = exc.headers.get("Retry-After") if exc.headers else None
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except (TypeError, ValueError):
            pass
    return min(30.0, (2.0 ** attempt) + random.random())


# ---------------------------------------------------------------------------
# Token bucket rate limiter
# ---------------------------------------------------------------------------


class TokenBucket:
    def __init__(self, per_period: float, period_seconds: float) -> None:
        self._per_period = per_period
        self._period_seconds = period_seconds
        self._tokens = per_period
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = max(0.0, now - self._updated)
                refill = elapsed * (self._per_period / self._period_seconds)
                if refill > 0:
                    self._tokens = min(self._per_period, self._tokens + refill)
                    self._updated = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                deficit = 1.0 - self._tokens
                wait = deficit * (self._period_seconds / self._per_period)
            time.sleep(min(wait, 5.0))


class RateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, TokenBucket] = {
            name: TokenBucket(spec["per_period"], spec["period_seconds"])
            for name, spec in RATE_BUCKETS.items()
        }

    def acquire(self, bucket_name: str) -> None:
        bucket = self._buckets.get(bucket_name) or self._buckets["default"]
        bucket.acquire()


# ---------------------------------------------------------------------------
# Header sanitization
# ---------------------------------------------------------------------------


_REDACT_HEADER_PATTERNS = (
    re.compile(r"(?i)(X-VO-Api-Key\s*:\s*)\S+"),
    re.compile(r"(?i)(X-VO-Api-Id\s*:\s*)\S+"),
    re.compile(r"(?i)(Authorization\s*:\s*\S+\s+)\S+"),
)


def redact_headers_text(text: str) -> str:
    redacted = text
    for pattern in _REDACT_HEADER_PATTERNS:
        redacted = pattern.sub(r"\1[REDACTED]", redacted)
    return redacted


# ---------------------------------------------------------------------------
# HTTP request
# ---------------------------------------------------------------------------


def request_json(
    method: str,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any] | None,
    *,
    rate_limiter: RateLimiter,
    rate_bucket: str,
) -> dict[str, Any]:
    data = None
    request_headers = {
        "Accept": "application/json",
        "User-Agent": _DEFAULT_USER_AGENT,
        **headers,
    }
    if body is not None and method in {"POST", "PUT", "PATCH"}:
        data = json.dumps(body).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=request_headers, method=method)
    max_attempts = _max_retries()
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        rate_limiter.acquire(rate_bucket)
        try:
            with urlopen(request, timeout=60) as response:  # noqa: S310 - operator-rendered API URL
                text = response.read().decode("utf-8")
                request_id = response.headers.get("X-VO-Request-Id", "")
                if not text:
                    return {"_request_id": request_id} if request_id else {}
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    return {"_raw_text": text[:4096], "_request_id": request_id}
                if isinstance(payload, dict) and request_id:
                    payload.setdefault("_request_id", request_id)
                if isinstance(payload, list):
                    return {"results": payload, "_request_id": request_id}
                return payload
        except HTTPError as exc:
            last_exc = exc
            if exc.code in _RETRYABLE_STATUSES and attempt < max_attempts - 1:
                time.sleep(retry_after_seconds(exc, attempt))
                continue
            try:
                error_text = exc.read().decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001 - best-effort error read
                error_text = ""
            error_text = redact_headers_text(error_text)[:4096]
            raise ApiError(
                f"{method} {url} failed with HTTP {exc.code}: {error_text}"
            ) from exc
        except URLError as exc:
            last_exc = exc
            if attempt < max_attempts - 1:
                time.sleep(min(30.0, (2.0 ** attempt) + random.random()))
                continue
            raise ApiError(f"{method} {url} failed: {exc.reason}") from exc
    raise ApiError(f"{method} {url} failed after {max_attempts} attempts: {last_exc}")


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def action_url(action: dict[str, Any], api_base: str) -> str:
    base = api_base.rstrip("/")
    return f"{base}{action.get('path', '')}"


def action_body(plan_dir: Path, action: dict[str, Any]) -> dict[str, Any] | None:
    payload_file = action.get("payload_file")
    if not payload_file:
        return action.get("body")
    return load_json(safe_plan_path(plan_dir, str(payload_file)))


def dry_run_result(plan: dict[str, Any], api_base: str) -> dict[str, Any]:
    sequence: list[dict[str, Any]] = []
    bucket_counts: dict[str, int] = defaultdict(int)
    for index, action in enumerate(plan.get("actions", []), start=1):
        bucket = str(action.get("rate_bucket", "default"))
        bucket_counts[bucket] += 1
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
                "rate_bucket": bucket,
                "service": "on_call",
                "url": action_url(action, api_base),
                "writes": bool(action.get("writes", False)),
            }
        )
    return {
        "ok": True,
        "dry_run": True,
        "api_base": api_base,
        "sequence": sequence,
        "bucket_counts": dict(bucket_counts),
    }


def apply_plan(
    plan_dir: Path,
    api_id: str,
    api_key_file: Path | None,
    *,
    dry_run: bool,
    api_base: str = _DEFAULT_API_BASE,
) -> dict[str, Any]:
    plan = load_json(plan_dir / "apply-plan.json")
    if plan.get("mode") != "splunk-oncall":
        raise ApiError("Only splunk-oncall apply plans can be applied.")
    actions = plan.get("actions") or []
    if not isinstance(actions, list):
        raise ApiError("apply-plan.json actions must be a list.")
    for index, action in enumerate(actions, start=1):
        if not isinstance(action, dict):
            raise ApiError(f"action {index} must be a JSON object.")
        validate_action(action, index)
    effective_api_base = api_base or str(plan.get("api_base") or _DEFAULT_API_BASE)
    if dry_run:
        return dry_run_result(plan, effective_api_base)
    if not api_id:
        raise ApiError("--api-id is required for live apply.")
    if api_key_file is None:
        raise ApiError("--api-key-file is required for live apply.")
    api_key = read_secret_file(api_key_file, "Splunk On-Call API key")
    headers = {"X-VO-Api-Id": api_id, "X-VO-Api-Key": api_key}
    rate_limiter = RateLimiter()

    responses: list[dict[str, Any]] = []
    for index, action in enumerate(actions, start=1):
        method = str(action.get("method", "GET")).upper()
        url = action_url(action, effective_api_base)
        body = action_body(plan_dir, action)
        bucket = str(action.get("rate_bucket", "default"))
        response = request_json(
            method,
            url,
            headers,
            body,
            rate_limiter=rate_limiter,
            rate_bucket=bucket,
        )
        responses.append(
            {
                "index": index,
                "action": action.get("action"),
                "method": method,
                "name": action.get("name"),
                "object_type": action.get("object_type"),
                "path": action.get("path"),
                "rate_bucket": bucket,
                "response": response,
            }
        )
    return {
        "ok": True,
        "dry_run": False,
        "api_base": effective_api_base,
        "responses": responses,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    apply_parser = subparsers.add_parser(
        "apply", help="Apply or dry-run a rendered Splunk On-Call plan."
    )
    apply_parser.add_argument("--plan-dir", required=True, type=Path)
    apply_parser.add_argument("--api-id", default="")
    apply_parser.add_argument("--api-key-file", type=Path)
    apply_parser.add_argument("--api-base", default=_DEFAULT_API_BASE)
    apply_parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)
    try:
        if args.command == "apply":
            result = apply_plan(
                args.plan_dir,
                args.api_id,
                args.api_key_file,
                dry_run=args.dry_run,
                api_base=args.api_base,
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
