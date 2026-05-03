#!/usr/bin/env python3
"""Splunk Cloud Platform <-> Splunk Observability Cloud Unified Identity pairing client.

Wraps two Splunk public APIs:

- ``acs observability pair / pairing-status-by-id / enable-capabilities /
  enable-centralized-rbac`` (ACS CLI 2.14.0+)
- ``POST /adminconfig/v2/observability/sso-pairing`` and
  ``GET  /adminconfig/v2/observability/sso-pairing/{pairing-id}`` (ACS REST)

Tokens are read from chmod-600 files only — never accepted as a CLI flag and
never written into ``apply-state.json``. The destructive
``enable-centralized-rbac`` action requires ``--i-accept-rbac-cutover``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _apply_state import append_step, has_step, read_secret_file  # noqa: E402


def _acs_available() -> bool:
    return shutil.which("acs") is not None


def _run_acs(args: list[str], env_extra: dict[str, str] | None = None) -> tuple[int, str, str]:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(
        ["acs", "--format", "structured", *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


def _rest_request(method: str, url: str, headers: dict[str, str], data: str | None = None) -> tuple[int, dict[str, Any]]:
    payload = data.encode("utf-8") if data else None
    req = urllib.request.Request(url, data=payload, method=method)
    for k, v in headers.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req) as resp:
        body = resp.read().decode("utf-8")
        try:
            return resp.status, json.loads(body)
        except json.JSONDecodeError:
            return resp.status, {"raw": body}


def pair(
    realm: str,
    admin_token_file: str,
    splunk_cloud_stack: str | None = None,
    splunk_cloud_admin_jwt_file: str | None = None,
    state_dir: Path | None = None,
) -> dict[str, Any]:
    """Pair the named Splunk Observability Cloud realm.

    Idempotent: if a previous run wrote a successful pair record under the
    same idempotency key, return ``skipped`` instead of re-pairing.
    """
    idem = f"pairing:{realm}:{splunk_cloud_stack or 'default'}"
    if state_dir is not None and has_step(state_dir, idem):
        return {"result": "skipped", "reason": "already-paired", "idempotency_key": idem}

    admin_token = read_secret_file(admin_token_file)

    if _acs_available():
        rc, out, err = _run_acs(
            ["observability", "pair", "--o11y-realm", realm, "--o11y-access-token", admin_token]
        )
        # Wipe the in-memory token and refuse to log it.
        admin_token = ""
        if rc != 0:
            if state_dir is not None:
                append_step(state_dir, "pairing", "pair", idem, "failed", notes=err.strip())
            return {"result": "failed", "stderr": err.strip(), "stdout": out.strip()}
        try:
            payload = json.loads(out) if out.strip() else {}
        except json.JSONDecodeError:
            payload = {"raw": out.strip()}
        if state_dir is not None:
            append_step(state_dir, "pairing", "pair", idem, "success", response=payload)
        return {"result": "success", "response": payload, "idempotency_key": idem}

    # ACS CLI not installed; fall back to REST.
    if not splunk_cloud_stack or not splunk_cloud_admin_jwt_file:
        return {
            "result": "failed",
            "reason": "acs CLI not installed and --splunk-cloud-admin-jwt-file not supplied for REST fallback",
        }
    jwt = read_secret_file(splunk_cloud_admin_jwt_file)
    url = f"https://admin.splunk.com/{splunk_cloud_stack}/adminconfig/v2/observability/sso-pairing"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {jwt}",
        "o11y-access-token": admin_token,
    }
    code, body = _rest_request("POST", url, headers, data="{}")
    admin_token = ""
    jwt = ""
    result = "success" if 200 <= code < 300 else "failed"
    if state_dir is not None:
        append_step(state_dir, "pairing", "pair", idem, result, response=body)
    return {"result": result, "status_code": code, "response": body, "idempotency_key": idem}


def status(
    pairing_id: str,
    admin_token_file: str,
    splunk_cloud_stack: str | None = None,
    splunk_cloud_admin_jwt_file: str | None = None,
    realm: str | None = None,
) -> dict[str, Any]:
    admin_token = read_secret_file(admin_token_file)
    if _acs_available():
        args = ["observability", "pairing-status-by-id", "--pairing-id", pairing_id, "--o11y-access-token", admin_token]
        if realm:
            args.extend(["--o11y-realm", realm])
        rc, out, err = _run_acs(args)
        admin_token = ""
        if rc != 0:
            return {"result": "failed", "stderr": err.strip(), "stdout": out.strip()}
        try:
            return {"result": "success", "response": json.loads(out)}
        except json.JSONDecodeError:
            return {"result": "success", "response": {"raw": out.strip()}}
    if not splunk_cloud_stack or not splunk_cloud_admin_jwt_file:
        return {
            "result": "failed",
            "reason": "acs CLI not installed and --splunk-cloud-admin-jwt-file not supplied for REST fallback",
        }
    jwt = read_secret_file(splunk_cloud_admin_jwt_file)
    url = f"https://admin.splunk.com/{splunk_cloud_stack}/adminconfig/v2/observability/sso-pairing/{pairing_id}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {jwt}",
        "o11y-access-token": admin_token,
    }
    code, body = _rest_request("GET", url, headers)
    admin_token = ""
    jwt = ""
    return {"result": "success" if 200 <= code < 300 else "failed", "status_code": code, "response": body}


def enable_capabilities(state_dir: Path | None = None) -> dict[str, Any]:
    idem = "centralized_rbac:enable_capabilities"
    if state_dir is not None and has_step(state_dir, idem):
        return {"result": "skipped", "reason": "already-applied", "idempotency_key": idem}
    if not _acs_available():
        return {"result": "failed", "reason": "acs CLI not installed"}
    rc, out, err = _run_acs(["observability", "enable-capabilities"])
    result = "success" if rc == 0 else "failed"
    if state_dir is not None:
        append_step(state_dir, "centralized_rbac", "enable_capabilities", idem, result, notes=(err or out).strip())
    return {"result": result, "stdout": out.strip(), "stderr": err.strip()}


def enable_centralized_rbac(
    admin_token_file: str,
    realm: str | None = None,
    state_dir: Path | None = None,
    cutover_ack: bool = False,
) -> dict[str, Any]:
    if not cutover_ack:
        return {
            "result": "failed",
            "reason": "enable-centralized-rbac is destructive; pass --i-accept-rbac-cutover to proceed.",
        }
    idem = f"centralized_rbac:enable_centralized_rbac:{realm or 'default'}"
    if state_dir is not None and has_step(state_dir, idem):
        return {"result": "skipped", "reason": "already-applied", "idempotency_key": idem}
    if not _acs_available():
        return {"result": "failed", "reason": "acs CLI not installed"}
    admin_token = read_secret_file(admin_token_file)
    args = ["observability", "enable-centralized-rbac", "--o11y-access-token", admin_token]
    if realm:
        args.extend(["--o11y-realm", realm])
    rc, out, err = _run_acs(args)
    admin_token = ""
    result = "success" if rc == 0 else "failed"
    if state_dir is not None:
        append_step(state_dir, "centralized_rbac", "enable_centralized_rbac", idem, result, notes=(err or out).strip())
    return {"result": result, "stdout": out.strip(), "stderr": err.strip()}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", default=None)
    parser.add_argument("--admin-token-file", default=None)
    parser.add_argument("--splunk-cloud-stack", default=None)
    parser.add_argument("--splunk-cloud-admin-jwt-file", default=None)
    parser.add_argument("--realm", default=None)
    parser.add_argument("--i-accept-rbac-cutover", action="store_true")

    sub = parser.add_subparsers(dest="action", required=True)
    pair_p = sub.add_parser("pair")
    pair_p.add_argument("--realm", required=True)

    status_p = sub.add_parser("status")
    status_p.add_argument("--pairing-id", required=True)

    sub.add_parser("enable-capabilities")
    sub.add_parser("enable-centralized-rbac")

    # Reject direct-secret flags so users get a friendly message.
    parser.add_argument("--token", help=argparse.SUPPRESS)
    parser.add_argument("--access-token", help=argparse.SUPPRESS)
    parser.add_argument("--admin-token", help=argparse.SUPPRESS)
    parser.add_argument("--api-token", help=argparse.SUPPRESS)
    parser.add_argument("--o11y-token", help=argparse.SUPPRESS)
    parser.add_argument("--sf-token", help=argparse.SUPPRESS)
    return parser.parse_args()


def _refuse_direct_secret(args: argparse.Namespace) -> None:
    for flag in ("token", "access_token", "admin_token", "api_token", "o11y_token", "sf_token"):
        if getattr(args, flag, None):
            print(
                f"refusing direct-secret flag --{flag.replace('_', '-')}; use --admin-token-file PATH (chmod 600).",
                file=sys.stderr,
            )
            raise SystemExit(2)


def main() -> int:
    args = parse_args()
    _refuse_direct_secret(args)
    state_dir = Path(args.state_dir) if args.state_dir else None
    try:
        if args.action == "pair":
            if not args.admin_token_file:
                raise RuntimeError("--admin-token-file is required for pair")
            result = pair(
                realm=args.realm,
                admin_token_file=args.admin_token_file,
                splunk_cloud_stack=args.splunk_cloud_stack,
                splunk_cloud_admin_jwt_file=args.splunk_cloud_admin_jwt_file,
                state_dir=state_dir,
            )
        elif args.action == "status":
            if not args.admin_token_file:
                raise RuntimeError("--admin-token-file is required for status")
            result = status(
                pairing_id=args.pairing_id,
                admin_token_file=args.admin_token_file,
                splunk_cloud_stack=args.splunk_cloud_stack,
                splunk_cloud_admin_jwt_file=args.splunk_cloud_admin_jwt_file,
                realm=args.realm,
            )
        elif args.action == "enable-capabilities":
            result = enable_capabilities(state_dir=state_dir)
        elif args.action == "enable-centralized-rbac":
            if not args.admin_token_file:
                raise RuntimeError("--admin-token-file is required for enable-centralized-rbac")
            result = enable_centralized_rbac(
                admin_token_file=args.admin_token_file,
                realm=args.realm,
                state_dir=state_dir,
                cutover_ack=args.i_accept_rbac_cutover,
            )
        else:  # pragma: no cover
            raise RuntimeError(f"unknown action: {args.action}")
    except Exception as exc:
        print(f"o11y_pairing_api FAILED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result.get("result") in {"success", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
