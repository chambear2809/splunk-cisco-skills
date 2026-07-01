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
import ssl
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _apply_state import append_step, redact  # noqa: E402


_INSECURE_WARNING_EMITTED = False


def _ssl_context() -> ssl.SSLContext | None:
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
    with urllib.request.urlopen(req, context=_ssl_context(), timeout=30) as resp:
        body = resp.read().decode("utf-8")
        try:
            return resp.status, json.loads(body)
        except json.JSONDecodeError:
            return resp.status, {"raw": body}


def status() -> dict:
    base = _splunk_base()
    url = f"{base.rstrip('/')}/services/admin/token-auth/tokens_auth?output_mode=json"
    code, body = _splunk_request("GET", url)
    return {"status_code": code, "body": redact(body)}


def _disabled_value(body: dict) -> bool:
    value = body.get("disabled")
    entries = body.get("entry")
    if value is None and isinstance(entries, list) and entries:
        first = entries[0]
        if isinstance(first, dict):
            content = first.get("content")
            if isinstance(content, dict):
                value = content.get("disabled")
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
    raise RuntimeError("token-auth status response did not contain a parseable disabled value")


def flip(enable: bool, state_dir: Path | None = None) -> dict:
    base = _splunk_base()
    url = f"{base.rstrip('/')}/services/admin/token-auth/tokens_auth"
    payload = {"disabled": "false" if enable else "true"}
    idem = f"token_auth:{base}:{'enable' if enable else 'disable'}"
    before = status()
    desired_disabled = not enable
    if _disabled_value(before["body"]) == desired_disabled:
        return {
            "result": "skipped",
            "reason": "already-converged",
            "status_code": before["status_code"],
        }
    code, body = _splunk_request("POST", f"{url}?output_mode=json", payload)
    after = status()
    if _disabled_value(after["body"]) != desired_disabled:
        if state_dir is not None:
            append_step(
                state_dir,
                "token_auth",
                "flip",
                idem,
                "failed",
                response={"post": body, "readback": after["body"]},
            )
        raise RuntimeError("token-auth POST returned but readback did not match requested state")
    result = "success"
    if state_dir is not None:
        append_step(
            state_dir,
            "token_auth",
            "flip",
            idem,
            result,
            response={"post": body, "readback": after["body"]},
        )
    return {
        "status_code": code,
        "body": redact(body),
        "readback_status_code": after["status_code"],
        "result": result,
    }


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
