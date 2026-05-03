#!/usr/bin/env python3
"""Discover Splunk Observability Cloud app REST client.

Configures the five Configurations tabs of the in-platform Discover app
through Splunk's UCC custom REST handlers, plus the Read permission grant
on the app for selected roles.

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
import ssl
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _apply_state import append_step, has_step, read_secret_file  # noqa: E402

DISCOVER_APP = "discover_splunk_observability_cloud"


def _ssl_ctx() -> ssl.SSLContext | None:
    if os.environ.get("SPLUNK_VERIFY_SSL", "true").lower() == "false":
        return ssl._create_unverified_context()
    return None


def _splunk_post(url: str, data: dict[str, str]) -> tuple[int, dict]:
    user = os.environ.get("SPLUNK_USER")
    password = os.environ.get("SPLUNK_PASS")
    if not user or not password:
        raise RuntimeError("SPLUNK_USER and SPLUNK_PASS must be set")
    payload = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode())
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, context=_ssl_ctx()) as resp:
        body = resp.read().decode("utf-8")
        try:
            return resp.status, json.loads(body)
        except json.JSONDecodeError:
            return resp.status, {"raw": body}


def _splunk_base() -> str:
    base = os.environ.get("SPLUNK_SEARCH_API_URI")
    if not base:
        raise RuntimeError("SPLUNK_SEARCH_API_URI must be set (https://host:8089)")
    return base.rstrip("/")


def configure_related_content_discovery(enabled: bool, state_dir: Path | None = None) -> dict:
    idem = "discover_app:related_content_discovery"
    if state_dir is not None and has_step(state_dir, idem):
        return {"result": "skipped", "idempotency_key": idem}
    url = f"{_splunk_base()}/servicesNS/nobody/{DISCOVER_APP}/related_content_discovery"
    code, body = _splunk_post(url, {"enabled": "1" if enabled else "0"})
    result = "success" if 200 <= code < 300 else "failed"
    if state_dir is not None:
        append_step(state_dir, "discover_app", "related_content_discovery", idem, result, response=body)
    return {"result": result, "status_code": code, "response": body}


def configure_field_aliasing(auto_field_mapping: bool, state_dir: Path | None = None) -> dict:
    idem = "discover_app:field_aliasing"
    if state_dir is not None and has_step(state_dir, idem):
        return {"result": "skipped", "idempotency_key": idem}
    url = f"{_splunk_base()}/servicesNS/nobody/{DISCOVER_APP}/field_aliasing"
    code, body = _splunk_post(url, {"auto_field_mapping": "1" if auto_field_mapping else "0"})
    result = "success" if 200 <= code < 300 else "failed"
    if state_dir is not None:
        append_step(state_dir, "discover_app", "field_aliasing", idem, result, response=body)
    return {"result": result, "status_code": code, "response": body}


def configure_automatic_ui_updates(enabled: bool, state_dir: Path | None = None) -> dict:
    idem = "discover_app:automatic_ui_updates"
    if state_dir is not None and has_step(state_dir, idem):
        return {"result": "skipped", "idempotency_key": idem}
    url = f"{_splunk_base()}/servicesNS/nobody/{DISCOVER_APP}/automatic_ui_updates"
    code, body = _splunk_post(url, {"enabled": "1" if enabled else "0"})
    result = "success" if 200 <= code < 300 else "failed"
    if state_dir is not None:
        append_step(state_dir, "discover_app", "automatic_ui_updates", idem, result, response=body)
    return {"result": result, "status_code": code, "response": body}


def configure_access_tokens(realm: str, token_file: str, state_dir: Path | None = None) -> dict:
    idem = f"discover_app:access_tokens:{realm}"
    if state_dir is not None and has_step(state_dir, idem):
        return {"result": "skipped", "idempotency_key": idem}
    token = read_secret_file(token_file)
    url = f"{_splunk_base()}/servicesNS/nobody/{DISCOVER_APP}/access_tokens"
    try:
        code, body = _splunk_post(url, {"realm": realm, "access_token": token})
    finally:
        token = ""  # zero out the token reference
    result = "success" if 200 <= code < 300 else "failed"
    if state_dir is not None:
        # Body is redacted by append_step, but we strip the field anyway for safety.
        sanitized = {"realm": realm, "status": "configured" if result == "success" else "failed"}
        append_step(state_dir, "discover_app", "access_tokens", idem, result, response=sanitized)
    return {"result": result, "status_code": code}


def grant_read_permission(roles: list[str], state_dir: Path | None = None) -> dict:
    idem = f"discover_app:read_permission:{','.join(sorted(roles))}"
    if state_dir is not None and has_step(state_dir, idem):
        return {"result": "skipped", "idempotency_key": idem}
    url = f"{_splunk_base()}/servicesNS/nobody/system/apps/local/{DISCOVER_APP}/permissions"
    payload = {"sharing": "app"}
    # Splunk REST accepts repeated perms.read=user,perms.read=power; serialize as one CSV value.
    payload["perms.read"] = ",".join(roles)
    code, body = _splunk_post(url, payload)
    result = "success" if 200 <= code < 300 else "failed"
    if state_dir is not None:
        append_step(state_dir, "discover_app", "read_permission", idem, result, response=body)
    return {"result": result, "status_code": code, "response": body}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", default=None)
    sub = parser.add_subparsers(dest="action", required=True)

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
        if args.action == "related-content-discovery":
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
