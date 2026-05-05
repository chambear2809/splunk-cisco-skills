#!/usr/bin/env python3
"""Splunk Observability Cloud /v2/integration client for AWSCloudWatch.

Wraps the public REST API documented at:
- https://dev.splunk.com/observability/reference/api/integrations/latest
- https://docs.splunk.com/en/splunk-observability-cloud/manage-data/connect-to-your-cloud-service-provider/connect-to-aws/connect-to-aws-using-the-splunk-api

Key conventions (verified against `o11y_dashboard_api.py` /
`o11y_native_api.py` patterns in this repo):

- Base URL: `https://api.<realm>.observability.splunkcloud.com/v2`.
- Auth header: `X-SF-Token: <admin user API access token>`.
- Token reads from chmod-600 file ONLY -- never accepted as a CLI flag.
- Retry on transient statuses {429, 502, 503, 504} with `Retry-After` honored,
  exponential backoff with jitter, `O11Y_MAX_RETRIES` env override.
- All apply steps recorded to ``apply-state.json`` (chmod 600) with secrets
  scrubbed via the ``_apply_state`` redactor.
- PUT body strips read-back fields (``metricStreamsSyncState``, ``largeVolume``,
  ``created``, ``lastUpdated``, ``creator``, ``lastUpdatedBy``,
  ``lastUpdatedByName``, ``createdByName``, ``id``).
"""

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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _apply_state import append_step, has_step, read_secret_file, redact  # noqa: E402

_RETRYABLE_STATUSES = {429, 502, 503, 504}

# Read-back fields the renderer strips before PUT.
READ_BACK_FIELDS: tuple[str, ...] = (
    "metricStreamsSyncState",
    "largeVolume",
    "created",
    "lastUpdated",
    "creator",
    "lastUpdatedBy",
    "lastUpdatedByName",
    "createdByName",
    "id",
)


class ApiError(Exception):
    """Raised when an API call fails."""


def _max_retries() -> int:
    raw = os.environ.get("O11Y_MAX_RETRIES")
    if raw is None:
        return 4
    try:
        value = int(raw)
    except ValueError:
        return 4
    return max(1, value)


def _retry_after_seconds(exc: HTTPError, attempt: int) -> float:
    retry_after = exc.headers.get("Retry-After") if exc.headers else None
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except (TypeError, ValueError):
            pass
    return min(30.0, (2.0 ** attempt) + random.random())


def _request(method: str, url: str, token: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    headers = {
        "X-SF-Token": token,
        "Accept": "application/json",
        "User-Agent": "splunk-observability-aws-integration/1 (+splunk-cisco-skills)",
    }
    data: bytes | None = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)

    max_attempts = _max_retries()
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            with urlopen(request, timeout=60) as response:  # noqa: S310 - operator-supplied URL
                text = response.read().decode("utf-8")
                if not text:
                    return {}
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return {"_raw": text}
        except HTTPError as exc:
            last_exc = exc
            if exc.code in _RETRYABLE_STATUSES and attempt < max_attempts - 1:
                time.sleep(_retry_after_seconds(exc, attempt))
                continue
            try:
                err_body = exc.read().decode("utf-8")
            except Exception:
                err_body = ""
            raise ApiError(f"{method} {url} -> HTTP {exc.code}: {err_body[:500]}") from exc
        except URLError as exc:
            last_exc = exc
            if attempt < max_attempts - 1:
                time.sleep(min(30.0, (2.0 ** attempt) + random.random()))
                continue
            raise ApiError(f"{method} {url} -> URLError: {exc}") from exc
    raise ApiError(f"{method} {url} exhausted retries: {last_exc}")


def _base_url(realm: str) -> str:
    return f"https://api.{realm}.observability.splunkcloud.com/v2"


def _strip_read_back(integration: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in integration.items() if k not in READ_BACK_FIELDS}


# ---------------------------------------------------------------------------
# Public API operations.
# ---------------------------------------------------------------------------


def list_aws_integrations(realm: str, token: str) -> list[dict[str, Any]]:
    """List all integrations and filter for type=AWSCloudWatch client-side."""
    url = f"{_base_url(realm)}/integration"
    response = _request("GET", url, token)
    items = response if isinstance(response, list) else response.get("items") or response.get("results") or []
    return [it for it in items if isinstance(it, dict) and it.get("type") == "AWSCloudWatch"]


def get_integration(realm: str, token: str, integration_id: str) -> dict[str, Any]:
    url = f"{_base_url(realm)}/integration/{integration_id}"
    return _request("GET", url, token)


def create_integration(realm: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{_base_url(realm)}/integration"
    body = _strip_read_back(payload)
    return _request("POST", url, token, body)


def update_integration(realm: str, token: str, integration_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{_base_url(realm)}/integration/{integration_id}"
    body = _strip_read_back(payload)
    return _request("PUT", url, token, body)


def delete_integration(realm: str, token: str, integration_id: str) -> dict[str, Any]:
    url = f"{_base_url(realm)}/integration/{integration_id}"
    return _request("DELETE", url, token)


# ---------------------------------------------------------------------------
# Higher-level operations used by the rendered apply scripts.
# ---------------------------------------------------------------------------


def upsert(
    realm: str,
    token: str,
    payload: dict[str, Any],
    state_dir: Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Idempotent create-or-update keyed on integration name."""
    name = payload.get("name") or ""
    if not name:
        raise ApiError("payload.name is required")
    idempotency_key = f"integration-upsert:{name}"
    if has_step(state_dir, idempotency_key):
        return {"result": "skipped", "name": name, "reason": "idempotency-key already recorded"}

    if dry_run:
        return {"result": "dry-run", "name": name, "would_send": redact(payload)}

    existing = list_aws_integrations(realm, token)
    match = next((i for i in existing if i.get("name") == name), None)

    if match:
        merged = {**match, **payload}
        merged["id"] = match["id"]
        # Always re-enable on update unless caller opted out.
        merged.setdefault("enabled", True)
        result = update_integration(realm, token, match["id"], merged)
        append_step(state_dir, "integration", "update", idempotency_key, "success", redact(result))
        return {"result": "updated", "name": name, "id": match["id"]}

    payload_with_disabled = {**payload, "enabled": False}
    result = create_integration(realm, token, payload_with_disabled)
    append_step(state_dir, "integration", "create", idempotency_key, "success", redact(result))
    return {"result": "created", "name": name, "id": result.get("id")}


def discover(realm: str, token: str, output_path: Path | None, state_dir: Path) -> dict[str, Any]:
    """Read all AWS integrations and write a redacted snapshot."""
    integrations = list_aws_integrations(realm, token)
    snapshot = {
        "discovered_at_realm": realm,
        "count": len(integrations),
        "integrations": [redact(i) for i in integrations],
    }
    if output_path:
        output_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    append_step(state_dir, "validation", "discover", f"discover:{realm}", "success", {"count": len(integrations)})
    return snapshot


def diff(spec_payload: dict[str, Any], live_payload: dict[str, Any]) -> dict[str, list[str]]:
    """Compare spec vs live and bucket per the drift-handling design."""
    safe_to_converge: list[str] = []
    operator_confirm: list[str] = []
    adopt_from_live: list[str] = []

    sensitive = {"useMetricStreamsSync", "metricStreamsManagedExternally", "regions", "authMethod", "roleArn"}
    spec_clean = _strip_read_back(spec_payload)
    live_clean = _strip_read_back(live_payload)

    spec_keys = set(spec_clean) - {"enabled", "id"}
    live_keys = set(live_clean) - {"enabled", "id"}

    for key in spec_keys:
        if key not in live_clean:
            safe_to_converge.append(f"{key} (spec sets {spec_clean[key]!r}, live unset)")
        elif spec_clean[key] != live_clean[key]:
            bucket = operator_confirm if key in sensitive else safe_to_converge
            bucket.append(f"{key} (spec={spec_clean[key]!r} live={live_clean[key]!r})")
    for key in live_keys - spec_keys:
        adopt_from_live.append(f"{key} (live={live_clean[key]!r}, spec leaves unset)")

    return {
        "safe_to_converge": safe_to_converge,
        "operator_confirm_required": operator_confirm,
        "adopt_from_live": adopt_from_live,
    }


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


_REJECTED_SECRET_FLAGS: tuple[str, ...] = (
    "--token", "--access-token", "--api-token", "--o11y-token", "--admin-token",
    "--sf-token", "--external-id", "--aws-access-key-id", "--aws-secret-access-key",
    "--aws-secret-key", "--password",
)


def _reject_direct_secret_flags() -> None:
    for arg in sys.argv[1:]:
        # Match exact flag (`--token`) or `--token=...` form.
        flag = arg.split("=", 1)[0]
        if flag in _REJECTED_SECRET_FLAGS:
            print(
                f"FAIL: refusing direct-secret flag {flag}. Use --token-file PATH "
                f"(chmod 600). For AWS access keys use --aws-access-key-id-file / "
                f"--aws-secret-access-key-file in setup.sh.",
                flush=True,
            )
            sys.exit(2)


def _parse() -> argparse.Namespace:
    _reject_direct_secret_flags()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--realm", required=True)
    p.add_argument("--token-file", required=True, help="chmod-600 file containing the admin user API access token")
    p.add_argument("--state-dir", required=True, help="rendered <output-dir>/state directory")
    p.add_argument("--payload-file", help="JSON payload for upsert")
    p.add_argument("--allow-loose-token-perms", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "command",
        choices=("list", "get", "upsert", "delete", "discover"),
    )
    p.add_argument("--integration-id", default="")
    p.add_argument("--output", default="")
    return p.parse_args()


def main() -> int:
    args = _parse()
    try:
        token = read_secret_file(args.token_file, allow_loose=args.allow_loose_token_perms)
    except PermissionError as exc:
        print(f"FAIL: {exc}", flush=True)
        return 2

    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)

    try:
        if args.command == "list":
            items = list_aws_integrations(args.realm, token)
            print(json.dumps([redact(i) for i in items], indent=2))
        elif args.command == "get":
            if not args.integration_id:
                raise ApiError("--integration-id is required for `get`")
            print(json.dumps(redact(get_integration(args.realm, token, args.integration_id)), indent=2))
        elif args.command == "upsert":
            if not args.payload_file:
                raise ApiError("--payload-file is required for `upsert`")
            payload = json.loads(Path(args.payload_file).read_text(encoding="utf-8"))
            result = upsert(args.realm, token, payload, state_dir, dry_run=args.dry_run)
            print(json.dumps(result, indent=2))
        elif args.command == "delete":
            if not args.integration_id:
                raise ApiError("--integration-id is required for `delete`")
            result = delete_integration(args.realm, token, args.integration_id)
            append_step(state_dir, "integration", "delete", f"integration-delete:{args.integration_id}", "success", redact(result))
            print(json.dumps(redact(result), indent=2))
        elif args.command == "discover":
            output_path = Path(args.output) if args.output else None
            snapshot = discover(args.realm, token, output_path, state_dir)
            print(json.dumps(snapshot, indent=2))
    except ApiError as exc:
        print(f"FAIL: {exc}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
