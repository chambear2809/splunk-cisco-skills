#!/usr/bin/env python3
"""Splunk Cloud Platform <-> Splunk Observability Cloud Unified Identity pairing client.

Wraps two Splunk public APIs:

- ``acs observability enable-capabilities`` (ACS CLI 2.14.0+; no secret token)
- ``POST /adminconfig/v2/observability/sso-pairing`` and
  ``GET  /adminconfig/v2/observability/sso-pairing/{pairing-id}`` (ACS REST)

Tokens are read from chmod-600 files only — never accepted as a CLI flag and
never written into ``apply-state.json``. Secret-bearing ACS CLI operations are
not invoked because current ACS syntax would put the O11y token on process argv.
The destructive ``enable-centralized-rbac`` action is an explicit fail-closed
handoff until a safe token-file capable transport exists.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _apply_state import (  # noqa: E402
    append_step,
    latest_step_response,
    read_secret_file,
    redact,
)


SAFE_STACK_RE = re.compile(r"^[A-Za-z0-9-]+$")
SAFE_PAIRING_ID_RE = re.compile(r"^[A-Za-z0-9._:-]+$")
UID_REALMS = {"us0", "us1", "eu0", "eu1", "eu2", "au0", "jp0", "sg0"}


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
    with urllib.request.urlopen(req, timeout=30) as resp:
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
    poll_timeout_seconds: int = 600,
    poll_interval_seconds: int = 5,
) -> dict[str, Any]:
    """Pair the named Splunk Observability Cloud realm.

    Idempotent after live readback.  A retained asynchronous job ID is resumed
    until it reaches a terminal state; a retry never creates a second job while
    the first job is still known.
    """
    idem = f"pairing:{realm}:{splunk_cloud_stack or 'default'}"
    if state_dir is None:
        raise ValueError("pairing requires --state-dir so asynchronous job IDs can be resumed safely")
    if realm not in UID_REALMS:
        raise ValueError(f"UID realm must be one of: {', '.join(sorted(UID_REALMS))}")
    if not splunk_cloud_stack or not splunk_cloud_admin_jwt_file:
        return {
            "result": "failed",
            "reason": (
                "safe pairing requires --splunk-cloud-stack and "
                "--splunk-cloud-admin-jwt-file for ACS REST; ACS CLI pairing "
                "would expose the O11y token on process argv"
            ),
        }
    if not SAFE_STACK_RE.fullmatch(splunk_cloud_stack):
        raise ValueError("splunk cloud stack must contain only letters, digits, or hyphens")
    previous = latest_step_response(
        state_dir, idem, {"success", "in_progress", "failed"}
    )
    if previous is not None:
        if (
            not isinstance(previous, dict)
            or not isinstance(previous.get("id"), str)
            or not previous["id"].strip()
        ):
            raise RuntimeError(
                "previous pairing state lacks a verifiable job ID; review the state file before retrying"
            )
        prior = _poll_pairing_status(
            pairing_id=previous["id"],
            admin_token_file=admin_token_file,
            splunk_cloud_stack=splunk_cloud_stack,
            splunk_cloud_admin_jwt_file=splunk_cloud_admin_jwt_file,
            timeout_seconds=poll_timeout_seconds,
            interval_seconds=poll_interval_seconds,
        )
        if prior["pairing_status"] == "SUCCESS":
            if state_dir is not None:
                append_step(
                    state_dir,
                    "pairing",
                    "pair",
                    idem,
                    "success",
                    response={
                        "id": previous["id"],
                        "status": "SUCCESS",
                        "status_code": prior["status_code"],
                    },
                )
            return {
                "result": "skipped",
                "reason": "already-paired-and-verified",
                "id": previous["id"],
                "idempotency_key": idem,
            }
        resumed_result = (
            "in_progress" if prior["pairing_status"] == "IN_PROGRESS" else "failed"
        )
        if state_dir is not None:
            append_step(
                state_dir,
                "pairing",
                "pair",
                idem,
                resumed_result,
                response={
                    "id": previous["id"],
                    "status": prior["pairing_status"],
                    "status_code": prior["status_code"],
                },
            )
        if resumed_result == "in_progress":
            return {
                "result": "in_progress",
                "reason": "poll-timeout; rerun to resume this pairing job",
                "id": previous["id"],
                "pairing_status": "IN_PROGRESS",
                "idempotency_key": idem,
            }
        raise RuntimeError(
            f"previous pairing job {previous['id']} is FAILED; refusing to create a duplicate"
        )

    admin_token = read_secret_file(admin_token_file)
    jwt = read_secret_file(splunk_cloud_admin_jwt_file)
    url = f"https://admin.splunk.com/{splunk_cloud_stack}/adminconfig/v2/observability/sso-pairing"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {jwt}",
        "o11y-access-token": admin_token,
    }
    try:
        code, body = _rest_request("POST", url, headers, data="{}")
    finally:
        admin_token = ""
        jwt = ""
    pairing_id = body.get("id") if isinstance(body, dict) else None
    if not isinstance(pairing_id, str) or not pairing_id.strip():
        raise RuntimeError("pairing POST succeeded but returned no job ID")
    final = _poll_pairing_status(
        pairing_id=pairing_id,
        admin_token_file=admin_token_file,
        splunk_cloud_stack=splunk_cloud_stack,
        splunk_cloud_admin_jwt_file=splunk_cloud_admin_jwt_file,
        timeout_seconds=poll_timeout_seconds,
        interval_seconds=poll_interval_seconds,
    )
    result = {
        "SUCCESS": "success",
        "IN_PROGRESS": "in_progress",
        "FAILED": "failed",
    }[final["pairing_status"]]
    state_response = {
        "id": pairing_id,
        "status": final["pairing_status"],
        "status_code": final["status_code"],
    }
    if state_dir is not None:
        append_step(state_dir, "pairing", "pair", idem, result, response=state_response)
    if result == "in_progress":
        return {
            "result": result,
            "reason": "poll-timeout; rerun to resume this pairing job",
            "status_code": code,
            "id": pairing_id,
            "pairing_status": final["pairing_status"],
            "idempotency_key": idem,
        }
    if result == "failed":
        raise RuntimeError(
            f"pairing job {pairing_id} completed with status {final['pairing_status']}"
        )
    return {
        "result": result,
        "status_code": code,
        "id": pairing_id,
        "pairing_status": final["pairing_status"],
        "idempotency_key": idem,
    }


def _pairing_status_value(body: dict[str, Any]) -> str:
    value: Any = body.get("status")
    if value is None and isinstance(body.get("data"), dict):
        value = body["data"].get("status")
    if not isinstance(value, str):
        raise RuntimeError("pairing status response did not contain a string status")
    normalized = value.strip().upper()
    if normalized not in {"SUCCESS", "FAILED", "IN_PROGRESS"}:
        raise RuntimeError(f"pairing status response returned unknown status {value!r}")
    return normalized


def _poll_pairing_status(
    pairing_id: str,
    admin_token_file: str,
    splunk_cloud_stack: str,
    splunk_cloud_admin_jwt_file: str,
    timeout_seconds: int,
    interval_seconds: int,
) -> dict[str, Any]:
    if timeout_seconds <= 0 or interval_seconds <= 0:
        raise ValueError("pairing poll timeout and interval must be positive")
    deadline = time.monotonic() + timeout_seconds
    while True:
        current = status(
            pairing_id=pairing_id,
            admin_token_file=admin_token_file,
            splunk_cloud_stack=splunk_cloud_stack,
            splunk_cloud_admin_jwt_file=splunk_cloud_admin_jwt_file,
        )
        if current["pairing_status"] in {"SUCCESS", "FAILED"}:
            return current
        if time.monotonic() >= deadline:
            return {
                **current,
                "pairing_status": "IN_PROGRESS",
                "timed_out": True,
            }
        time.sleep(min(interval_seconds, max(0.0, deadline - time.monotonic())))


def status(
    pairing_id: str,
    admin_token_file: str,
    splunk_cloud_stack: str | None = None,
    splunk_cloud_admin_jwt_file: str | None = None,
    realm: str | None = None,
) -> dict[str, Any]:
    if not splunk_cloud_stack or not splunk_cloud_admin_jwt_file:
        return {
            "result": "failed",
            "reason": (
                "safe pairing status requires --splunk-cloud-stack and "
                "--splunk-cloud-admin-jwt-file for ACS REST; ACS CLI status "
                "would expose the O11y token on process argv"
            ),
        }
    if not SAFE_STACK_RE.fullmatch(splunk_cloud_stack):
        raise ValueError("splunk cloud stack must contain only letters, digits, or hyphens")
    if not SAFE_PAIRING_ID_RE.fullmatch(pairing_id):
        raise ValueError("pairing ID must be a safe non-empty URL path segment")
    admin_token = read_secret_file(admin_token_file)
    jwt = read_secret_file(splunk_cloud_admin_jwt_file)
    url = f"https://admin.splunk.com/{splunk_cloud_stack}/adminconfig/v2/observability/sso-pairing/{pairing_id}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {jwt}",
        "o11y-access-token": admin_token,
    }
    try:
        code, body = _rest_request("GET", url, headers)
    finally:
        admin_token = ""
        jwt = ""
    pairing_status = _pairing_status_value(body)
    result = "success" if pairing_status == "SUCCESS" else (
        "failed" if pairing_status == "FAILED" else "in_progress"
    )
    return {
        "result": result,
        "status_code": code,
        "pairing_status": pairing_status,
        "response": redact(body),
    }


def enable_capabilities(state_dir: Path | None = None) -> dict[str, Any]:
    idem = "centralized_rbac:enable_capabilities"
    if not _acs_available():
        return {"result": "failed", "reason": "acs CLI not installed"}
    rc, out, err = _run_acs(["observability", "enable-capabilities"])
    result = "success" if rc == 0 else "failed"
    if state_dir is not None:
        append_step(state_dir, "centralized_rbac", "enable_capabilities", idem, result, notes=(err or out).strip())
    return {"result": result, "stdout": out.strip(), "stderr": err.strip()}


def enable_centralized_rbac(
    realm: str | None = None,
    state_dir: Path | None = None,
) -> dict[str, Any]:
    idem = f"centralized_rbac:enable_centralized_rbac:{realm or 'default'}"
    result = "failed"
    out = ""
    err = (
        "enable-centralized-rbac is not automated because ACS CLI requires "
        "--o11y-access-token on process argv and no safe REST/token-file "
        "transport is implemented in this skill yet"
    )
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
    parser.add_argument("--poll-timeout-seconds", type=int, default=600)
    parser.add_argument("--poll-interval-seconds", type=int, default=5)

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
                poll_timeout_seconds=args.poll_timeout_seconds,
                poll_interval_seconds=args.poll_interval_seconds,
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
            result = enable_centralized_rbac(
                realm=args.realm,
                state_dir=state_dir,
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
