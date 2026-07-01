#!/usr/bin/env python3
"""Discover Splunk Observability Cloud app REST client.

Configures the API-backed Discover app surfaces through Splunk's UCC custom
REST handlers, plus the Read permission grant on the app for selected roles.
The Test related content tab remains UI-only.

Endpoints (all under ``servicesNS/nobody/discover_splunk_observability_cloud``):

- ``related_content_discovery``  (Tab 1: Related Content discovery toggle)
- ``field_aliasing``             (Tab 3: Field aliasing + Auto Field Mapping)
- ``automatic_ui_updates``       (Tab 4: Automatic UI updates toggle)
- ``access_tokens``              (Tab 5: Realm + token write — token from chmod-600 file)

Plus ``servicesNS/nobody/system/apps/local/discover_splunk_observability_cloud/permissions``
for the Read permission grant.

Tokens are read from chmod-600 files only — never accepted as a CLI flag and
never written into apply-state.json.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import ssl
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _apply_state import append_step, read_secret_file, redact  # noqa: E402

DISCOVER_APP = "discover_splunk_observability_cloud"
SAFE_ROLE_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
O11Y_API_REALMS = {"us0", "us1", "us2", "eu0", "eu1", "eu2", "au0", "jp0", "sg0"}
_INSECURE_WARNING_EMITTED = False


def _ssl_ctx() -> ssl.SSLContext | None:
    global _INSECURE_WARNING_EMITTED
    if os.environ.get("SPLUNK_VERIFY_SSL", "true").lower() in {"false", "0", "no"}:
        if not _INSECURE_WARNING_EMITTED:
            print(
                "WARNING: SPLUNK_VERIFY_SSL disables certificate verification; the peer is not authenticated and credentials may be intercepted.",
                file=sys.stderr,
            )
            _INSECURE_WARNING_EMITTED = True
        return ssl._create_unverified_context()
    ca_file = os.environ.get("SPLUNK_CA_CERT")
    if ca_file:
        path = Path(ca_file)
        if not path.is_file():
            raise RuntimeError(f"SPLUNK_CA_CERT is not readable: {path}")
        return ssl.create_default_context(cafile=str(path))
    return None


def _splunk_request(
    method: str, url: str, data: dict[str, str] | None = None
) -> tuple[int, dict]:
    user = os.environ.get("SPLUNK_USER")
    password = os.environ.get("SPLUNK_PASS")
    if not user or not password:
        raise RuntimeError("SPLUNK_USER and SPLUNK_PASS must be set")
    payload = urllib.parse.urlencode(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=payload, method=method)
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode())
    if data is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, context=_ssl_ctx(), timeout=30) as resp:
        body = resp.read().decode("utf-8")
        try:
            return resp.status, json.loads(body)
        except json.JSONDecodeError:
            return resp.status, {"raw": body}


def _splunk_post(url: str, data: dict[str, str]) -> tuple[int, dict]:
    return _splunk_request("POST", url, data)


def _splunk_get(url: str) -> tuple[int, dict]:
    separator = "&" if "?" in url else "?"
    return _splunk_request("GET", f"{url}{separator}output_mode=json")


def _values_for_key(value: object, key: str) -> list[object]:
    found: list[object] = []
    if isinstance(value, dict):
        for current_key, current_value in value.items():
            if current_key == key:
                found.append(current_value)
            found.extend(_values_for_key(current_value, key))
    elif isinstance(value, list):
        for item in value:
            found.extend(_values_for_key(item, key))
    return found


def _as_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes"}:
            return True
        if lowered in {"0", "false", "no"}:
            return False
    return None


def _require_boolean_readback(body: dict, key: str, expected: bool) -> None:
    observed = {_as_bool(value) for value in _values_for_key(body, key)}
    if expected not in observed:
        raise RuntimeError(f"readback for {key} did not match requested value {expected}")


def _splunk_base() -> str:
    base = os.environ.get("SPLUNK_SEARCH_API_URI")
    if not base:
        raise RuntimeError("SPLUNK_SEARCH_API_URI must be set (https://host:8089)")
    parsed = urllib.parse.urlsplit(base)
    try:
        parsed.port
    except ValueError as exc:
        raise RuntimeError("SPLUNK_SEARCH_API_URI contains an invalid port") from exc
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or any(ch.isspace() for ch in base)
    ):
        raise RuntimeError(
            "SPLUNK_SEARCH_API_URI must be an absolute https://host[:port] URL without embedded credentials, path, query, fragment, or whitespace"
        )
    return base.rstrip("/")


def _permission_roles(body: dict) -> set[str]:
    observed_roles: set[str] = set()
    permission_values = _values_for_key(body, "perms.read")
    for perms in _values_for_key(body, "perms"):
        if isinstance(perms, dict) and "read" in perms:
            permission_values.append(perms["read"])
    for value in permission_values:
        if isinstance(value, str):
            observed_roles.update(item.strip() for item in value.split(",") if item.strip())
        elif isinstance(value, list):
            observed_roles.update(str(item).strip() for item in value if str(item).strip())
    return observed_roles


def configure_related_content_discovery(enabled: bool, state_dir: Path | None = None) -> dict:
    idem = "discover_app:related_content_discovery"
    url = f"{_splunk_base()}/servicesNS/nobody/{DISCOVER_APP}/related_content_discovery"
    _splunk_get(url)
    code, body = _splunk_post(url, {"enabled": "1" if enabled else "0"})
    _, readback = _splunk_get(url)
    _require_boolean_readback(readback, "enabled", enabled)
    result = "success"
    if state_dir is not None:
        append_step(state_dir, "discover_app", "related_content_discovery", idem, result, response=readback)
    return {
        "result": result,
        "status_code": code,
        "response": redact(body),
        "readback": redact(readback),
    }


def configure_field_aliasing(auto_field_mapping: bool, state_dir: Path | None = None) -> dict:
    idem = "discover_app:field_aliasing"
    url = f"{_splunk_base()}/servicesNS/nobody/{DISCOVER_APP}/field_aliasing"
    _splunk_get(url)
    code, body = _splunk_post(url, {"auto_field_mapping": "1" if auto_field_mapping else "0"})
    _, readback = _splunk_get(url)
    _require_boolean_readback(readback, "auto_field_mapping", auto_field_mapping)
    result = "success"
    if state_dir is not None:
        append_step(state_dir, "discover_app", "field_aliasing", idem, result, response=readback)
    return {
        "result": result,
        "status_code": code,
        "response": redact(body),
        "readback": redact(readback),
    }


def configure_automatic_ui_updates(enabled: bool, state_dir: Path | None = None) -> dict:
    idem = "discover_app:automatic_ui_updates"
    url = f"{_splunk_base()}/servicesNS/nobody/{DISCOVER_APP}/automatic_ui_updates"
    _splunk_get(url)
    code, body = _splunk_post(url, {"enabled": "1" if enabled else "0"})
    _, readback = _splunk_get(url)
    _require_boolean_readback(readback, "enabled", enabled)
    result = "success"
    if state_dir is not None:
        append_step(state_dir, "discover_app", "automatic_ui_updates", idem, result, response=readback)
    return {
        "result": result,
        "status_code": code,
        "response": redact(body),
        "readback": redact(readback),
    }


def configure_access_tokens(realm: str, token_file: str, state_dir: Path | None = None) -> dict:
    if realm not in O11Y_API_REALMS:
        raise ValueError(f"realm must be one of: {', '.join(sorted(O11Y_API_REALMS))}")
    idem = f"discover_app:access_tokens:{realm}"
    url = f"{_splunk_base()}/servicesNS/nobody/{DISCOVER_APP}/access_tokens"
    _splunk_get(url)
    token = read_secret_file(token_file)
    try:
        code, body = _splunk_post(url, {"realm": realm, "access_token": token})
    finally:
        token = ""  # zero out the token reference
    _, readback = _splunk_get(url)
    realms = {str(value) for value in _values_for_key(readback, "realm")}
    if realm not in realms:
        raise RuntimeError(f"access-token readback did not contain configured realm {realm!r}")
    result = "success"
    if state_dir is not None:
        # Body is redacted by append_step, but we strip the field anyway for safety.
        sanitized = {"realm": realm, "status": "configured" if result == "success" else "failed"}
        sanitized["readback_realm"] = realm
        append_step(state_dir, "discover_app", "access_tokens", idem, result, response=sanitized)
    return {"result": result, "status_code": code, "readback_realm": realm}


def grant_read_permission(roles: list[str], state_dir: Path | None = None) -> dict:
    if not roles or any(not SAFE_ROLE_RE.fullmatch(role) for role in roles):
        raise ValueError("roles must be non-empty and contain only letters, digits, dot, underscore, or hyphen")
    idem = f"discover_app:read_permission:{','.join(sorted(roles))}"
    url = f"{_splunk_base()}/servicesNS/nobody/system/apps/local/{DISCOVER_APP}/permissions"
    _, before = _splunk_get(url)
    requested = set(roles)
    existing_roles = _permission_roles(before)
    if not existing_roles:
        raise RuntimeError(
            "Discover app permission readback contained no parseable existing readers; refusing a potentially destructive ACL replacement"
        )
    merged_roles = sorted(existing_roles | requested)
    payload = {"sharing": "app"}
    # Preserve existing readers: this endpoint replaces, rather than appends,
    # the ACL value when perms.read is supplied.
    payload["perms.read"] = ",".join(merged_roles)
    code, body = _splunk_post(url, payload)
    _, readback = _splunk_get(url)
    observed_roles = _permission_roles(readback)
    missing = sorted(set(merged_roles) - observed_roles)
    if missing:
        raise RuntimeError(f"Discover app read-permission readback is missing roles: {', '.join(missing)}")
    result = "success"
    if state_dir is not None:
        append_step(state_dir, "discover_app", "read_permission", idem, result, response=readback)
    return {
        "result": result,
        "status_code": code,
        "response": redact(body),
        "readback": redact(readback),
    }


def preflight() -> dict:
    """Read every endpoint used by the composed Discover apply before mutation."""
    base = f"{_splunk_base()}/servicesNS/nobody/{DISCOVER_APP}"
    endpoints = {
        "related_content_discovery": f"{base}/related_content_discovery",
        "field_aliasing": f"{base}/field_aliasing",
        "automatic_ui_updates": f"{base}/automatic_ui_updates",
        "read_permission": (
            f"{_splunk_base()}/servicesNS/nobody/system/apps/local/"
            f"{DISCOVER_APP}/permissions"
        ),
    }
    statuses: dict[str, int] = {}
    for name, url in endpoints.items():
        code, _ = _splunk_get(url)
        statuses[name] = code
    return {"result": "success", "endpoints": statuses}


def preflight_access_tokens() -> dict:
    """Read the service-account pairing endpoint without exposing its body."""
    url = f"{_splunk_base()}/servicesNS/nobody/{DISCOVER_APP}/access_tokens"
    code, _ = _splunk_get(url)
    return {"result": "success", "status_code": code}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", default=None)
    sub = parser.add_subparsers(dest="action", required=True)

    sub.add_parser("preflight")
    sub.add_parser("preflight-access-tokens")

    rcd = sub.add_parser("related-content-discovery")
    rcd.add_argument("--enabled", choices=("true", "false"), default="true")

    fa = sub.add_parser("field-aliasing")
    fa.add_argument("--auto-field-mapping", choices=("true", "false"), default="true")

    au = sub.add_parser("automatic-ui-updates")
    au.add_argument("--enabled", choices=("true", "false"), default="true")

    at = sub.add_parser("access-tokens")
    at.add_argument("--realm", required=True)
    at.add_argument("--token-file", required=True)

    perm = sub.add_parser("read-permission")
    perm.add_argument("--roles", required=True, help="Comma-separated roles to grant Read on the Discover app.")

    parser.add_argument("--token", help=argparse.SUPPRESS)
    parser.add_argument("--access-token", help=argparse.SUPPRESS)
    parser.add_argument("--api-token", help=argparse.SUPPRESS)
    parser.add_argument("--o11y-token", help=argparse.SUPPRESS)
    parser.add_argument("--sf-token", help=argparse.SUPPRESS)
    parser.add_argument("--password", help=argparse.SUPPRESS)
    return parser.parse_args()


def _refuse_direct_secret(args: argparse.Namespace) -> None:
    for flag in ("token", "access_token", "api_token", "o11y_token", "sf_token", "password"):
        if getattr(args, flag, None):
            print(
                f"refusing direct-secret flag --{flag.replace('_', '-')}; use --token-file PATH (chmod 600).",
                file=sys.stderr,
            )
            raise SystemExit(2)


def main() -> int:
    args = parse_args()
    _refuse_direct_secret(args)
    state_dir = Path(args.state_dir) if args.state_dir else None
    try:
        if args.action == "preflight":
            result = preflight()
        elif args.action == "preflight-access-tokens":
            result = preflight_access_tokens()
        elif args.action == "related-content-discovery":
            result = configure_related_content_discovery(args.enabled == "true", state_dir=state_dir)
        elif args.action == "field-aliasing":
            result = configure_field_aliasing(args.auto_field_mapping == "true", state_dir=state_dir)
        elif args.action == "automatic-ui-updates":
            result = configure_automatic_ui_updates(args.enabled == "true", state_dir=state_dir)
        elif args.action == "access-tokens":
            result = configure_access_tokens(args.realm, args.token_file, state_dir=state_dir)
        elif args.action == "read-permission":
            result = grant_read_permission([r.strip() for r in args.roles.split(",") if r.strip()], state_dir=state_dir)
        else:  # pragma: no cover
            raise RuntimeError(f"unknown action: {args.action}")
    except Exception as exc:
        print(f"discover_app_api FAILED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result.get("result") in {"success", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
