#!/usr/bin/env python3
"""Splunk Observability Cloud /v2/integration client for Azure (type=Azure).

Key conventions:
- Base URL: https://api.<realm>.observability.splunkcloud.com/v2
- Auth: X-SF-Token (admin user API access token, chmod-600 file)
- appId / secretKey: read from chmod-600 files; never passed as CLI flags
- Retry on {429, 502, 503, 504} with Retry-After honored
- PUT body strips read-back fields (created, lastUpdated, creator, lastUpdatedBy, id)
- appId + secretKey are redacted on GET by the Splunk API; drift detection uses
  SHA-256 hash comparison vs state/credential-hashes.json
"""

from __future__ import annotations

import argparse
import hashlib
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

# Fields the Splunk API returns on GET but that must be stripped before PUT.
READ_BACK_FIELDS: tuple[str, ...] = (
    "created", "lastUpdated", "creator", "lastUpdatedBy",
    "lastUpdatedByName", "createdByName", "id",
)

# Fields that are write-only (redacted on GET); local hash comparison is needed.
CREDENTIAL_FIELDS: tuple[str, ...] = ("appId", "secretKey")


class ApiError(Exception):
    """Raised when an API call fails."""


def _max_retries() -> int:
    raw = os.environ.get("O11Y_MAX_RETRIES")
    if raw is None:
        return 4
    try:
        return max(1, int(raw))
    except ValueError:
        return 4


def _retry_after(exc: HTTPError, attempt: int) -> float:
    ra = exc.headers.get("Retry-After") if exc.headers else None
    if ra:
        try:
            return max(0.0, float(ra))
        except (TypeError, ValueError):
            pass
    return min(30.0, (2.0 ** attempt) + random.random())


def _request(method: str, url: str, token: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    headers = {
        "X-SF-Token": token,
        "Accept": "application/json",
        "User-Agent": "splunk-observability-azure-integration/1 (+splunk-cisco-skills)",
    }
    data: bytes | None = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = Request(url, data=data, headers=headers, method=method)
    max_attempts = _max_retries()
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            with urlopen(req, timeout=60) as resp:  # noqa: S310
                text = resp.read().decode("utf-8")
                if not text:
                    return {}
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return {"_raw": text}
        except HTTPError as exc:
            last_exc = exc
            if exc.code in _RETRYABLE_STATUSES and attempt < max_attempts - 1:
                time.sleep(_retry_after(exc, attempt))
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
# Credential hash helpers.
# ---------------------------------------------------------------------------


def _sha256_file(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return ""
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _load_cred_hashes(state_dir: Path) -> dict[str, str]:
    p = state_dir / "credential-hashes.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cred_hashes(state_dir: Path, hashes: dict[str, str]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    p = state_dir / "credential-hashes.json"
    p.write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def check_credential_drift(
    state_dir: Path,
    app_id_file: str,
    secret_file: str,
) -> list[str]:
    """Compare local file hashes vs stored hashes. Returns warnings on mismatch."""
    stored = _load_cred_hashes(state_dir)
    warnings: list[str] = []
    for field, path in (("app_id_sha256", app_id_file), ("secret_sha256", secret_file)):
        if not path:
            continue
        current = _sha256_file(path)
        saved = stored.get(field, "")
        if saved and saved != current:
            warnings.append(
                f"credential drift: {field} hash changed since last apply "
                f"(last={saved[:12]}... current={current[:12]}...). Re-apply to update."
            )
    return warnings


# ---------------------------------------------------------------------------
# Public API operations.
# ---------------------------------------------------------------------------


def list_azure_integrations(realm: str, token: str) -> list[dict[str, Any]]:
    url = f"{_base_url(realm)}/integration"
    response = _request("GET", url, token)
    items = (
        response if isinstance(response, list)
        else response.get("items") or response.get("results") or []
    )
    return [it for it in items if isinstance(it, dict) and it.get("type") == "Azure"]


def get_integration(realm: str, token: str, integration_id: str) -> dict[str, Any]:
    url = f"{_base_url(realm)}/integration/{integration_id}"
    return _request("GET", url, token)


def create_integration(realm: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{_base_url(realm)}/integration"
    return _request("POST", url, token, _strip_read_back(payload))


def update_integration(realm: str, token: str, integration_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{_base_url(realm)}/integration/{integration_id}"
    return _request("PUT", url, token, _strip_read_back(payload))


def delete_integration(realm: str, token: str, integration_id: str) -> dict[str, Any]:
    url = f"{_base_url(realm)}/integration/{integration_id}"
    return _request("DELETE", url, token)


def disable_integration(realm: str, token: str, integration_id: str) -> dict[str, Any]:
    live = get_integration(realm, token, integration_id)
    live["enabled"] = False
    return update_integration(realm, token, integration_id, live)


# ---------------------------------------------------------------------------
# Higher-level operations.
# ---------------------------------------------------------------------------


def upsert(
    realm: str,
    token: str,
    payload: dict[str, Any],
    state_dir: Path,
    app_id_file: str = "",
    secret_file: str = "",
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Idempotent create-or-update keyed on integration name.

    After a successful apply, stores SHA-256 hashes of the credential files
    in state/credential-hashes.json for later drift detection.
    """
    name = payload.get("name") or ""
    if not name:
        raise ApiError("payload.name is required")
    idempotency_key = f"azure-upsert:{name}"
    if has_step(state_dir, idempotency_key):
        return {"result": "skipped", "name": name, "reason": "idempotency-key already recorded"}

    # Resolve actual credentials from files.
    if app_id_file:
        try:
            payload = {**payload, "appId": read_secret_file(app_id_file)}
        except PermissionError as exc:
            raise ApiError(str(exc)) from exc
    if secret_file:
        try:
            payload = {**payload, "secretKey": read_secret_file(secret_file)}
        except PermissionError as exc:
            raise ApiError(str(exc)) from exc

    if dry_run:
        return {"result": "dry-run", "name": name, "would_send": redact(payload)}

    existing = list_azure_integrations(realm, token)
    match = next((i for i in existing if i.get("name") == name), None)

    if match:
        merged = {**match, **payload}
        merged["id"] = match["id"]
        merged.setdefault("enabled", True)
        result = update_integration(realm, token, match["id"], merged)
        append_step(state_dir, "integration", "update", idempotency_key, "success", redact(result))
        _record_credential_hashes(state_dir, app_id_file, secret_file)
        return {"result": "updated", "name": name, "id": match["id"]}

    payload_disabled = {**payload, "enabled": False}
    result = create_integration(realm, token, payload_disabled)
    append_step(state_dir, "integration", "create", idempotency_key, "success", redact(result))
    _record_credential_hashes(state_dir, app_id_file, secret_file)
    return {"result": "created", "name": name, "id": result.get("id")}


def _record_credential_hashes(state_dir: Path, app_id_file: str, secret_file: str) -> None:
    hashes: dict[str, str] = {}
    if app_id_file:
        hashes["app_id_sha256"] = _sha256_file(app_id_file)
    if secret_file:
        hashes["secret_sha256"] = _sha256_file(secret_file)
    if hashes:
        _save_cred_hashes(state_dir, hashes)


def discover(realm: str, token: str, output_path: Path | None, state_dir: Path) -> dict[str, Any]:
    integrations = list_azure_integrations(realm, token)
    snapshot = {
        "discovered_at_realm": realm,
        "count": len(integrations),
        "integrations": [redact(i) for i in integrations],
        "note": "appId and secretKey are redacted by the Splunk API on GET. "
                "Drift detection uses state/credential-hashes.json.",
    }
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    append_step(
        state_dir, "validation", "discover", f"azure-discover:{realm}", "success",
        {"count": len(integrations)},
    )
    return snapshot


def disable_by_name(realm: str, token: str, name: str, state_dir: Path) -> dict[str, Any]:
    existing = list_azure_integrations(realm, token)
    match = next((i for i in existing if i.get("name") == name), None)
    if not match:
        return {"result": "not_found", "name": name}
    result = disable_integration(realm, token, match["id"])
    append_step(state_dir, "integration", "disable", f"azure-disable:{name}", "success", redact(result))
    return {"result": "disabled", "name": name, "id": match["id"]}


def delete_by_name(realm: str, token: str, name: str, state_dir: Path) -> dict[str, Any]:
    existing = list_azure_integrations(realm, token)
    match = next((i for i in existing if i.get("name") == name), None)
    if not match:
        return {"result": "not_found", "name": name}
    delete_integration(realm, token, match["id"])
    append_step(state_dir, "integration", "delete", f"azure-delete:{name}", "success", {})
    return {"result": "deleted", "name": name, "id": match["id"]}


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


_REJECTED_SECRET_FLAGS: tuple[str, ...] = (
    "--token", "--access-token", "--api-token", "--o11y-token", "--admin-token",
    "--sf-token", "--app-id", "--app-secret", "--client-secret", "--password", "--secret",
)


def _reject_direct_secret_flags() -> None:
    for arg in sys.argv[1:]:
        flag = arg.split("=", 1)[0]
        if flag in _REJECTED_SECRET_FLAGS:
            print(
                f"FAIL: refusing direct-secret flag {flag}. Use --token-file, --app-id-file, "
                f"or --secret-file (all chmod 600).",
                flush=True,
            )
            sys.exit(2)


def _parse() -> argparse.Namespace:
    _reject_direct_secret_flags()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--realm", required=True)
    p.add_argument("--token-file", required=True)
    p.add_argument("--state-dir", required=True)
    p.add_argument("--payload-file", default="")
    p.add_argument("--app-id-file", default="")
    p.add_argument("--secret-file", default="")
    p.add_argument("--allow-loose-token-perms", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--integration-id", default="")
    p.add_argument("--output", default="")
    p.add_argument(
        "command",
        choices=("list", "get", "upsert", "disable", "delete", "discover", "check-drift"),
    )
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
            items = list_azure_integrations(args.realm, token)
            print(json.dumps([redact(i) for i in items], indent=2))

        elif args.command == "get":
            if not args.integration_id:
                raise ApiError("--integration-id is required for `get`")
            print(json.dumps(redact(get_integration(args.realm, token, args.integration_id)), indent=2))

        elif args.command == "upsert":
            if not args.payload_file:
                raise ApiError("--payload-file is required for `upsert`")
            payload = json.loads(Path(args.payload_file).read_text(encoding="utf-8"))
            result = upsert(
                args.realm, token, payload, state_dir,
                app_id_file=args.app_id_file,
                secret_file=args.secret_file,
                dry_run=args.dry_run,
            )
            print(json.dumps(result, indent=2))

        elif args.command == "disable":
            if not args.integration_id:
                raise ApiError("--integration-id is required for `disable`")
            result = disable_integration(args.realm, token, args.integration_id)
            append_step(state_dir, "integration", "disable",
                        f"azure-disable:{args.integration_id}", "success", redact(result))
            print(json.dumps(redact(result), indent=2))

        elif args.command == "delete":
            if not args.integration_id:
                raise ApiError("--integration-id is required for `delete`")
            delete_integration(args.realm, token, args.integration_id)
            append_step(state_dir, "integration", "delete",
                        f"azure-delete:{args.integration_id}", "success", {})
            print(json.dumps({"result": "deleted", "id": args.integration_id}, indent=2))

        elif args.command == "discover":
            output_path = Path(args.output) if args.output else None
            snapshot = discover(args.realm, token, output_path, state_dir)
            print(json.dumps(snapshot, indent=2))

        elif args.command == "check-drift":
            if not args.app_id_file and not args.secret_file:
                raise ApiError("--app-id-file or --secret-file required for `check-drift`")
            warnings = check_credential_drift(state_dir, args.app_id_file, args.secret_file)
            if warnings:
                for w in warnings:
                    print(f"WARN: {w}", flush=True)
                return 1
            print("OK: no credential drift detected")

    except ApiError as exc:
        print(f"FAIL: {exc}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
