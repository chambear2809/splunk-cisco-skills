#!/usr/bin/env python3
"""Splunk Observability Cloud /v2/integration client for GCP (type=GCP).

Key conventions:
- Base URL: https://api.<realm>.observability.splunkcloud.com/v2
- Auth: X-SF-Token (admin user API access token, chmod-600 file)
- projectKey: read from chmod-600 files; never passed as CLI flags
- workloadIdentityFederationConfig: compact JSON read from Splunk's official
  generated chmod-600 gcp_wif_config.json; never reconstructed by this client
- Retry on {429, 502, 503, 504} with Retry-After honored
- PUT body strips read-back fields (created, lastUpdated, creator, lastUpdatedBy, id)
- projectKey is write-only (redacted on GET) by the Splunk API; drift detection uses
  SHA-256 hash comparison vs state/credential-hashes.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import stat
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _apply_state import append_step, read_secret_file, redact  # noqa: E402


_RETRYABLE_STATUSES = {429, 502, 503, 504}

# Fields the Splunk API returns on GET but that must be stripped before PUT.
READ_BACK_FIELDS: tuple[str, ...] = (
    "created", "lastUpdated", "creator", "lastUpdatedBy",
    "lastUpdatedByName", "createdByName", "id",
)

# Fields treated as credential material. projectKey is known to be write-only;
# the generated WIF document is also redacted from local state and logs.
CREDENTIAL_FIELDS: tuple[str, ...] = ("projectKey", "workloadIdentityFederationConfig")


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
        "User-Agent": "splunk-observability-gcp-integration/1 (+splunk-cisco-skills)",
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


def _validate_projects_contract(payload: dict[str, Any]) -> None:
    projects = payload.get("projects")
    if not isinstance(projects, dict):
        raise ApiError("payload.projects must be an object containing syncMode")
    sync_mode = projects.get("syncMode")
    if sync_mode not in ("ALL", "SELECTED"):
        raise ApiError("payload.projects.syncMode must be ALL or SELECTED")
    project_ids = projects.get("projectIds", [])
    if not isinstance(project_ids, list) or not all(
        isinstance(project_id, str) and project_id
        for project_id in project_ids
    ):
        raise ApiError("payload.projects.projectIds must be a list of non-empty strings")
    if sync_mode == "ALL" and project_ids:
        raise ApiError("payload.projects.projectIds must be empty when syncMode=ALL")
    if sync_mode == "SELECTED" and not project_ids:
        raise ApiError("payload.projects.projectIds is required when syncMode=SELECTED")


# ---------------------------------------------------------------------------
# Credential hash helpers.
# ---------------------------------------------------------------------------


def _sha256_file(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return ""
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load_wif_config_file(path: str) -> str:
    """Validate and compact Splunk's official generated GCP WIF JSON file.

    The document is intentionally treated as opaque. This client validates only
    its file security and JSON envelope, then sends the complete object as the
    string-valued ``workloadIdentityFederationConfig`` API field.
    """
    p = Path(path)
    if p.name != "gcp_wif_config.json":
        raise ApiError(
            "--wif-config-file must reference Splunk's official generated "
            "gcp_wif_config.json"
        )
    try:
        metadata = p.lstat()
    except OSError as exc:
        raise ApiError(f"WIF config file is missing or unreadable: {p}: {exc}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ApiError(f"WIF config file must be a regular file, not a symlink: {p}")
    mode = stat.S_IMODE(metadata.st_mode)
    if mode != 0o600:
        raise ApiError(f"WIF config file {p} must have mode 600, found {oct(mode)}")
    if metadata.st_size == 0:
        raise ApiError(f"WIF config file is empty: {p}")
    try:
        document = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ApiError(f"WIF config file is not valid UTF-8 JSON: {p}: {exc}") from exc
    if not isinstance(document, dict) or not document:
        raise ApiError(f"WIF config file must contain a non-empty JSON object: {p}")
    return json.dumps(document, separators=(",", ":"), ensure_ascii=False)


def _load_cred_hashes(state_dir: Path) -> dict[str, Any]:
    p = state_dir / "credential-hashes.json"
    if not p.exists():
        return {}
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ApiError(f"credential hash state is unreadable or invalid: {p}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ApiError(f"credential hash state must be a JSON object: {p}")
    for field in ("project_key_sha256", "wif_config_sha256"):
        if field in payload and not isinstance(payload[field], dict):
            raise ApiError(f"credential hash state field {field} must be an object: {p}")
    return payload


def _save_cred_hashes(state_dir: Path, hashes: dict[str, Any]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    p = state_dir / "credential-hashes.json"
    p.write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
    os.chmod(p, 0o600)


def check_credential_drift(
    state_dir: Path,
    key_files: list[str],
    wif_config_file: str = "",
) -> list[str]:
    """Compare local file hashes vs stored hashes. Returns warnings on mismatch."""
    stored = _load_cred_hashes(state_dir)
    stored_keys = stored.get("project_key_sha256", {})
    warnings: list[str] = []
    for path in key_files:
        if not path:
            continue
        current = _sha256_file(path)
        saved = stored_keys.get(path, "")
        if saved and saved != current:
            warnings.append(
                f"credential drift: key_file {path} hash changed since last apply "
                f"(last={saved[:12]}... current={current[:12]}...). Re-apply to update."
            )
    if wif_config_file:
        current = _sha256_file(wif_config_file)
        saved_wif = stored.get("wif_config_sha256", {}).get(wif_config_file, "")
        if saved_wif and saved_wif != current:
            warnings.append(
                f"credential drift: WIF config {wif_config_file} hash changed since last apply "
                f"(last={saved_wif[:12]}... current={current[:12]}...). Re-apply to update."
            )
    return warnings


# ---------------------------------------------------------------------------
# Public API operations.
# ---------------------------------------------------------------------------


def list_gcp_integrations(realm: str, token: str) -> list[dict[str, Any]]:
    url = f"{_base_url(realm)}/integration"
    response = _request("GET", url, token)
    items = (
        response if isinstance(response, list)
        else response.get("items") or response.get("results") or []
    )
    return [it for it in items if isinstance(it, dict) and it.get("type") == "GCP"]


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
    key_files: list[str] | None = None,
    wif_config_file: str = "",
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Idempotent create-or-update keyed on integration name.

    After a successful apply, stores SHA-256 hashes of the key files or WIF
    configuration in state/credential-hashes.json for later drift detection.
    """
    name = payload.get("name") or ""
    if not name:
        raise ApiError("payload.name is required")
    _validate_projects_contract(payload)
    idempotency_key = f"gcp-upsert:{name}"

    # Resolve write-only authentication fields before any live API operation.
    # This guarantees missing, malformed, or insecure credential files fail
    # before list/create/update can run.
    auth_method = payload.get("authMethod")
    if auth_method == "SERVICE_ACCOUNT_KEY":
        if wif_config_file:
            raise ApiError("--wif-config-file cannot be used with SERVICE_ACCOUNT_KEY")
        if not key_files:
            raise ApiError(
                "SERVICE_ACCOUNT_KEY apply requires exactly one --key-file per projectServiceKeys entry"
            )
        entries = [entry for entry in payload.get("projectServiceKeys", []) if isinstance(entry, dict)]
        if len(key_files) != len(entries):
            raise ApiError(
                f"received {len(key_files)} --key-file value(s) for {len(entries)} "
                "projectServiceKeys entries; supply exactly one file per project in spec order"
            )
        new_psk = []
        for entry, key_file in zip(entries, key_files):
            try:
                project_key = read_secret_file(key_file)
            except (OSError, PermissionError, ValueError) as exc:
                raise ApiError(str(exc)) from exc
            new_psk.append({**entry, "projectKey": project_key})
        payload = {**payload, "projectServiceKeys": new_psk}
        payload.pop("workloadIdentityFederationConfig", None)
        payload.pop("workloadIdentityPoolId", None)
        payload.pop("workloadIdentityProviderId", None)
    elif auth_method == "WORKLOAD_IDENTITY_FEDERATION":
        if key_files:
            raise ApiError("--key-file cannot be used with WORKLOAD_IDENTITY_FEDERATION")
        if not wif_config_file:
            raise ApiError(
                "WORKLOAD_IDENTITY_FEDERATION apply requires --wif-config-file "
                "pointing to the official gcp_wif_config.json"
            )
        compact_wif_config = load_wif_config_file(wif_config_file)
        payload = {
            **payload,
            "workloadIdentityFederationConfig": compact_wif_config,
        }
        payload.pop("projectServiceKeys", None)
        payload.pop("workloadIdentityPoolId", None)
        payload.pop("workloadIdentityProviderId", None)
    else:
        raise ApiError(
            "payload.authMethod must be SERVICE_ACCOUNT_KEY or WORKLOAD_IDENTITY_FEDERATION"
        )

    if dry_run:
        return {"result": "dry-run", "name": name, "would_send": redact(payload)}

    existing = list_gcp_integrations(realm, token)
    match = next((i for i in existing if i.get("name") == name), None)

    if match:
        merged = {**match, **payload}
        if auth_method == "WORKLOAD_IDENTITY_FEDERATION":
            merged.pop("projectServiceKeys", None)
            merged.pop("workloadIdentityPoolId", None)
            merged.pop("workloadIdentityProviderId", None)
        else:
            merged.pop("workloadIdentityFederationConfig", None)
            merged.pop("workloadIdentityPoolId", None)
            merged.pop("workloadIdentityProviderId", None)
        merged["id"] = match["id"]
        merged["enabled"] = bool(payload.get("enabled", True))
        result = update_integration(realm, token, match["id"], merged)
        append_step(state_dir, "integration", "update", idempotency_key, "success", redact(result))
        _record_credential_hashes(state_dir, key_files or [], wif_config_file)
        return {"result": "updated", "name": name, "id": match["id"]}

    payload_enabled = {**payload, "enabled": bool(payload.get("enabled", True))}
    result = create_integration(realm, token, payload_enabled)
    append_step(state_dir, "integration", "create", idempotency_key, "success", redact(result))
    _record_credential_hashes(state_dir, key_files or [], wif_config_file)
    return {"result": "created", "name": name, "id": result.get("id")}


def _record_credential_hashes(
    state_dir: Path,
    key_files: list[str],
    wif_config_file: str = "",
) -> None:
    hashes: dict[str, str] = {}
    for path in key_files:
        if path:
            hashes[path] = _sha256_file(path)
    if hashes or wif_config_file:
        existing = _load_cred_hashes(state_dir)
        existing_keys = existing.get("project_key_sha256", {})
        existing_keys.update(hashes)
        existing_wif = existing.get("wif_config_sha256", {})
        if wif_config_file:
            existing_wif[wif_config_file] = _sha256_file(wif_config_file)
        _save_cred_hashes(
            state_dir,
            {
                "project_key_sha256": existing_keys,
                "wif_config_sha256": existing_wif,
            },
        )


def discover(realm: str, token: str, output_path: Path | None, state_dir: Path) -> dict[str, Any]:
    integrations = list_gcp_integrations(realm, token)
    snapshot = {
        "discovered_at_realm": realm,
        "count": len(integrations),
        "integrations": [redact(i) for i in integrations],
        "note": "projectKey is write-only and redacted by the Splunk API on GET. "
                "The WIF config is also treated as credential material. Drift detection "
                "uses state/credential-hashes.json.",
    }
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    append_step(
        state_dir, "validation", "discover", f"gcp-discover:{realm}", "success",
        {"count": len(integrations)},
    )
    return snapshot


def disable_by_name(realm: str, token: str, name: str, state_dir: Path) -> dict[str, Any]:
    if not name:
        raise ApiError("payload.name is required for disable-by-name")
    existing = list_gcp_integrations(realm, token)
    match = next((i for i in existing if i.get("name") == name), None)
    if not match:
        return {"result": "not_found", "name": name}
    result = disable_integration(realm, token, match["id"])
    append_step(state_dir, "integration", "disable", f"gcp-disable:{name}", "success", redact(result))
    return {"result": "disabled", "name": name, "id": match["id"]}


def delete_by_name(realm: str, token: str, name: str, state_dir: Path) -> dict[str, Any]:
    if not name:
        raise ApiError("payload.name is required for delete-by-name")
    existing = list_gcp_integrations(realm, token)
    match = next((i for i in existing if i.get("name") == name), None)
    if not match:
        return {"result": "not_found", "name": name}
    delete_integration(realm, token, match["id"])
    append_step(state_dir, "integration", "delete", f"gcp-delete:{name}", "success", {})
    return {"result": "deleted", "name": name, "id": match["id"]}


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


_REJECTED_SECRET_FLAGS: tuple[str, ...] = (
    "--token", "--access-token", "--api-token", "--o11y-token", "--admin-token",
    "--sf-token", "--project-key", "--api-key", "--secret", "--password",
    "--wif-config", "--workload-identity-federation-config",
)


def _reject_direct_secret_flags() -> None:
    for arg in sys.argv[1:]:
        flag = arg.split("=", 1)[0]
        if flag in _REJECTED_SECRET_FLAGS:
            print(
                f"FAIL: refusing direct-secret flag {flag}. Use --token-file, --key-file, "
                f"or --wif-config-file (all mode 600).",
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
    p.add_argument("--key-file", action="append", default=[], dest="key_files",
                   help="GCP SA key file (chmod 600); may be repeated for multi-project")
    p.add_argument(
        "--wif-config-file",
        default="",
        help="Official Splunk-generated gcp_wif_config.json file (mode 600)",
    )
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
    except (OSError, PermissionError, ValueError) as exc:
        print(f"FAIL: {exc}", flush=True)
        return 2

    state_dir = Path(args.state_dir)

    try:
        if args.command == "list":
            items = list_gcp_integrations(args.realm, token)
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
                key_files=args.key_files or None,
                wif_config_file=args.wif_config_file,
                dry_run=args.dry_run,
            )
            print(json.dumps(result, indent=2))

        elif args.command == "disable":
            if args.integration_id:
                result = disable_integration(args.realm, token, args.integration_id)
                append_step(state_dir, "integration", "disable",
                            f"gcp-disable:{args.integration_id}", "success", redact(result))
                print(json.dumps(redact(result), indent=2))
            elif args.payload_file:
                payload = json.loads(Path(args.payload_file).read_text(encoding="utf-8"))
                print(json.dumps(disable_by_name(args.realm, token, str(payload.get("name", "")), state_dir), indent=2))
            else:
                raise ApiError("--integration-id or --payload-file is required for `disable`")

        elif args.command == "delete":
            if args.integration_id:
                delete_integration(args.realm, token, args.integration_id)
                append_step(state_dir, "integration", "delete",
                            f"gcp-delete:{args.integration_id}", "success", {})
                print(json.dumps({"result": "deleted", "id": args.integration_id}, indent=2))
            elif args.payload_file:
                payload = json.loads(Path(args.payload_file).read_text(encoding="utf-8"))
                print(json.dumps(delete_by_name(args.realm, token, str(payload.get("name", "")), state_dir), indent=2))
            else:
                raise ApiError("--integration-id or --payload-file is required for `delete`")

        elif args.command == "discover":
            output_path = Path(args.output) if args.output else None
            snapshot = discover(args.realm, token, output_path, state_dir)
            print(json.dumps(snapshot, indent=2))

        elif args.command == "check-drift":
            if not args.key_files and not args.wif_config_file:
                raise ApiError("--key-file or --wif-config-file is required for `check-drift`")
            if args.wif_config_file:
                load_wif_config_file(args.wif_config_file)
            warnings = check_credential_drift(
                state_dir,
                args.key_files,
                args.wif_config_file,
            )
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
