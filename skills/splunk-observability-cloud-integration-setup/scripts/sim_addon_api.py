#!/usr/bin/env python3
"""Splunk Infrastructure Monitoring Add-on (Splunk_TA_sim) UCC REST client.

Wraps the add-on's UCC custom REST handlers for:

- ``/servicesNS/nobody/Splunk_TA_sim/splunk_infrastructure_monitoring_account``
  (account create / list / check connection / enable Data Collection toggle)
- ``/servicesNS/nobody/Splunk_TA_sim/data/inputs/splunk_infrastructure_monitoring_data_streams``
  (modular input create / list)

Org tokens are read from chmod-600 files only — never accepted as a CLI flag
and never written into apply-state.json.

Includes the MTS sizing preflight that compares the requested SignalFlow
program's per-entity MTS estimate against the 250,000-MTS-per-computation
hard cap before issuing the modular-input create call.
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

MTS_PER_MODULAR_INPUT_CAP = 250000


def _ssl_ctx() -> ssl.SSLContext | None:
    if os.environ.get("SPLUNK_VERIFY_SSL", "true").lower() == "false":
        return ssl._create_unverified_context()
    return None


def _splunk_request(method: str, url: str, data: dict[str, str] | None = None) -> tuple[int, dict]:
    user = os.environ.get("SPLUNK_USER")
    password = os.environ.get("SPLUNK_PASS")
    if not user or not password:
        raise RuntimeError("SPLUNK_USER and SPLUNK_PASS must be set")
    payload = urllib.parse.urlencode(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=payload, method=method)
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode())
    if data is not None:
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


def list_accounts(state_dir: Path | None = None) -> dict:
    url = f"{_splunk_base()}/servicesNS/nobody/Splunk_TA_sim/splunk_infrastructure_monitoring_account?output_mode=json"
    code, body = _splunk_request("GET", url)
    return {"status_code": code, "response": body}


def create_account(
    name: str,
    realm: str,
    org_token_file: str,
    job_start_rate: int = 60,
    event_search_rate: int = 30,
    state_dir: Path | None = None,
) -> dict:
    """Create a SIM Add-on account through the UCC REST handler.

    Idempotent: skipped if a previous run wrote a successful step under the
    same idempotency key.
    """
    idem = f"sim_addon:account:{name}:{realm}"
    if state_dir is not None and has_step(state_dir, idem):
        return {"result": "skipped", "idempotency_key": idem}
    org_token = read_secret_file(org_token_file)
    url = f"{_splunk_base()}/servicesNS/nobody/Splunk_TA_sim/splunk_infrastructure_monitoring_account"
    payload = {
        "name": name,
        "realm": realm,
        "access_token": org_token,
        "job_start_rate": str(job_start_rate),
        "event_search_rate": str(event_search_rate),
    }
    try:
        code, body = _splunk_request("POST", url, payload)
    finally:
        org_token = ""
    result = "success" if 200 <= code < 300 else "failed"
    if state_dir is not None:
        sanitized = {"name": name, "realm": realm, "status": "configured" if result == "success" else "failed"}
        append_step(state_dir, "sim_addon", "create_account", idem, result, response=sanitized)
    return {"result": result, "status_code": code}


def check_connection(name: str, state_dir: Path | None = None) -> dict:
    url = f"{_splunk_base()}/servicesNS/nobody/Splunk_TA_sim/splunk_infrastructure_monitoring_account/{urllib.parse.quote(name)}/check_connection"
    code, body = _splunk_request("POST", url, {})
    result = "success" if 200 <= code < 300 else "failed"
    if state_dir is not None:
        append_step(state_dir, "sim_addon", "check_connection", f"sim_addon:check:{name}", result, response=body)
    return {"result": result, "status_code": code, "response": body}


def enable_account(name: str, enabled: bool, state_dir: Path | None = None) -> dict:
    url = f"{_splunk_base()}/servicesNS/nobody/Splunk_TA_sim/splunk_infrastructure_monitoring_account/{urllib.parse.quote(name)}/data_collection"
    code, body = _splunk_request("POST", url, {"enabled": "1" if enabled else "0"})
    result = "success" if 200 <= code < 300 else "failed"
    if state_dir is not None:
        append_step(state_dir, "sim_addon", "enable_account", f"sim_addon:enable:{name}:{enabled}", result, response=body)
    return {"result": result, "status_code": code, "response": body}


def preflight_mts(name: str, mts_per_entity: int, expected_entities: int) -> dict:
    estimated = mts_per_entity * expected_entities
    if estimated > MTS_PER_MODULAR_INPUT_CAP:
        return {
            "result": "failed",
            "reason": (
                f"modular-input '{name}' MTS estimate {estimated} exceeds hard cap "
                f"{MTS_PER_MODULAR_INPUT_CAP}; reduce expected_entities or split the input."
            ),
            "estimated_mts": estimated,
        }
    return {"result": "ok", "estimated_mts": estimated}


def create_modular_input(
    name: str,
    index: str,
    account: str,
    signalflow_program: str,
    interval_seconds: int = 300,
    enabled: bool = True,
    state_dir: Path | None = None,
) -> dict:
    if name.upper().startswith("SAMPLE_"):
        return {
            "result": "failed",
            "reason": "Splunk Infrastructure Monitoring Add-on never runs SAMPLE_-prefixed programs; pass a name without the prefix.",
        }
    idem = f"sim_addon:modinput:{name}"
    if state_dir is not None and has_step(state_dir, idem):
        return {"result": "skipped", "idempotency_key": idem}
    url = f"{_splunk_base()}/servicesNS/nobody/Splunk_TA_sim/data/inputs/splunk_infrastructure_monitoring_data_streams"
    payload = {
        "name": name,
        "index": index,
        "account": account,
        "interval": str(interval_seconds),
        "disabled": "0" if enabled else "1",
        "signalflow_program": signalflow_program,
    }
    code, body = _splunk_request("POST", url, payload)
    result = "success" if 200 <= code < 300 else "failed"
    if state_dir is not None:
        append_step(state_dir, "sim_addon", "create_modular_input", idem, result, response={"name": name, "status": result})
    return {"result": result, "status_code": code, "response": body}


def list_modular_inputs() -> dict:
    url = f"{_splunk_base()}/servicesNS/nobody/Splunk_TA_sim/data/inputs/splunk_infrastructure_monitoring_data_streams?output_mode=json"
    code, body = _splunk_request("GET", url)
    return {"status_code": code, "response": body}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", default=None)
    sub = parser.add_subparsers(dest="action", required=True)

    sub.add_parser("list-accounts")

    create = sub.add_parser("create-account")
    create.add_argument("--name", required=True)
    create.add_argument("--realm", required=True)
    create.add_argument("--org-token-file", required=True)
    create.add_argument("--job-start-rate", type=int, default=60)
    create.add_argument("--event-search-rate", type=int, default=30)

    check = sub.add_parser("check-connection")
    check.add_argument("--name", required=True)

    enable = sub.add_parser("enable-account")
    enable.add_argument("--name", required=True)
    enable.add_argument("--enabled", choices=("true", "false"), default="true")

    preflight = sub.add_parser("preflight-mts")
    preflight.add_argument("--name", required=True)
    preflight.add_argument("--mts-per-entity", type=int, required=True)
    preflight.add_argument("--expected-entities", type=int, required=True)

    modinput = sub.add_parser("create-modular-input")
    modinput.add_argument("--name", required=True)
    modinput.add_argument("--index", required=True)
    modinput.add_argument("--account", required=True)
    modinput.add_argument("--signalflow-program", required=True)
    modinput.add_argument("--interval-seconds", type=int, default=300)
    modinput.add_argument("--enabled", choices=("true", "false"), default="true")

    sub.add_parser("list-modular-inputs")

    parser.add_argument("--token", help=argparse.SUPPRESS)
    parser.add_argument("--access-token", help=argparse.SUPPRESS)
    parser.add_argument("--api-token", help=argparse.SUPPRESS)
    parser.add_argument("--o11y-token", help=argparse.SUPPRESS)
    parser.add_argument("--org-token", help=argparse.SUPPRESS)
    parser.add_argument("--sf-token", help=argparse.SUPPRESS)
    parser.add_argument("--password", help=argparse.SUPPRESS)
    return parser.parse_args()


def _refuse_direct_secret(args: argparse.Namespace) -> None:
    for flag in ("token", "access_token", "api_token", "o11y_token", "org_token", "sf_token", "password"):
        if getattr(args, flag, None):
            print(
                f"refusing direct-secret flag --{flag.replace('_', '-')}; use --org-token-file PATH (chmod 600).",
                file=sys.stderr,
            )
            raise SystemExit(2)


def main() -> int:
    args = parse_args()
    _refuse_direct_secret(args)
    state_dir = Path(args.state_dir) if args.state_dir else None
    try:
        if args.action == "list-accounts":
            result = list_accounts(state_dir=state_dir)
        elif args.action == "create-account":
            result = create_account(
                name=args.name,
                realm=args.realm,
                org_token_file=args.org_token_file,
                job_start_rate=args.job_start_rate,
                event_search_rate=args.event_search_rate,
                state_dir=state_dir,
            )
        elif args.action == "check-connection":
            result = check_connection(args.name, state_dir=state_dir)
        elif args.action == "enable-account":
            result = enable_account(args.name, args.enabled == "true", state_dir=state_dir)
        elif args.action == "preflight-mts":
            result = preflight_mts(args.name, args.mts_per_entity, args.expected_entities)
        elif args.action == "create-modular-input":
            result = create_modular_input(
                name=args.name,
                index=args.index,
                account=args.account,
                signalflow_program=args.signalflow_program,
                interval_seconds=args.interval_seconds,
                enabled=args.enabled == "true",
                state_dir=state_dir,
            )
        elif args.action == "list-modular-inputs":
            result = list_modular_inputs()
        else:  # pragma: no cover
            raise RuntimeError(f"unknown action: {args.action}")
    except Exception as exc:
        print(f"sim_addon_api FAILED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0 if (isinstance(result, dict) and result.get("result") in {"success", "skipped", "ok", None}) else 1


if __name__ == "__main__":
    raise SystemExit(main())
