#!/usr/bin/env python3
"""Token authentication state read + flip for Splunk Cloud Platform / Enterprise.

Endpoints:
- GET  ``{search-api-uri}/services/admin/token-auth/tokens_auth`` -> ``disabled`` field
- POST ``{search-api-uri}/services/admin/token-auth/tokens_auth -d disabled=false|true``

Required capability: ``edit_tokens_settings``. The flip takes effect immediately
and does not require a Splunk restart. Splunk credentials come from the Splunk
REST helper environment variables (``SPLUNK_SEARCH_API_URI``, ``SPLUNK_USER``,
``SPLUNK_PASS``). Never accept a password as a CLI flag.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _apply_state import append_step, has_step  # noqa: E402


def _splunk_request(method: str, url: str, data: dict | None = None) -> tuple[int, dict]:
    user = os.environ.get("SPLUNK_USER")
    password = os.environ.get("SPLUNK_PASS")
    if not user or not password:
        raise RuntimeError("SPLUNK_USER and SPLUNK_PASS must be set")
    payload = urllib.parse.urlencode(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=payload, method=method)
    import base64
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode())
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    ctx = None
    if os.environ.get("SPLUNK_VERIFY_SSL", "true").lower() == "false":
        import ssl
        ctx = ssl._create_unverified_context()
    with urllib.request.urlopen(req, context=ctx) as resp:
        body = resp.read().decode("utf-8")
        try:
            return resp.status, json.loads(body)
        except json.JSONDecodeError:
            return resp.status, {"raw": body}


def status() -> dict:
    base = os.environ.get("SPLUNK_SEARCH_API_URI")
    if not base:
        raise RuntimeError("SPLUNK_SEARCH_API_URI must be set (https://host:8089)")
    url = f"{base.rstrip('/')}/services/admin/token-auth/tokens_auth?output_mode=json"
    code, body = _splunk_request("GET", url)
    return {"status_code": code, "body": body}


def flip(enable: bool, state_dir: Path | None = None) -> dict:
    base = os.environ.get("SPLUNK_SEARCH_API_URI")
    if not base:
        raise RuntimeError("SPLUNK_SEARCH_API_URI must be set (https://host:8089)")
    url = f"{base.rstrip('/')}/services/admin/token-auth/tokens_auth"
    payload = {"disabled": "false" if enable else "true"}
    idem = f"token_auth:{base}:{'enable' if enable else 'disable'}"
    if state_dir is not None and has_step(state_dir, idem):
        return {"result": "skipped", "reason": "already-applied"}
    code, body = _splunk_request("POST", url, payload)
    result = "success" if 200 <= code < 300 else "failed"
    if state_dir is not None:
        append_step(state_dir, "token_auth", "flip", idem, result, response=body)
    return {"status_code": code, "body": body, "result": result}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", default=None, help="Path to <rendered>/state for apply-state.json bookkeeping.")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("status")
    enable = sub.add_parser("enable")
    enable.set_defaults(enable=True)
    disable = sub.add_parser("disable")
    disable.set_defaults(enable=False)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    state_dir = Path(args.state_dir) if args.state_dir else None
    try:
        if args.action == "status":
            print(json.dumps(status(), indent=2))
        else:
            print(json.dumps(flip(args.enable, state_dir=state_dir), indent=2))
    except Exception as exc:  # pragma: no cover (CLI surface)
        print(f"token_auth_api FAILED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
