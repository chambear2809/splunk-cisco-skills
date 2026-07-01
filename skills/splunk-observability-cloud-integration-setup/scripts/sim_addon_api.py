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
from _apply_state import append_step, read_secret_file, redact  # noqa: E402

MTS_PER_MODULAR_INPUT_CAP = 250000
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


def _splunk_request(method: str, url: str, data: dict[str, str] | None = None) -> tuple[int, dict]:
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


def _entries(body: dict) -> list[dict]:
    entries = body.get("entry")
    if not isinstance(entries, list):
        return []
    result: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        merged: dict = {}
        content = entry.get("content")
        if isinstance(content, dict):
            merged.update(content)
        for key in ("name", "title"):
            if isinstance(entry.get(key), str):
                merged.setdefault("name", entry[key])
        result.append(merged)
    return result


def _find_entry(body: dict, name: str) -> dict | None:
    for entry in _entries(body):
        if str(entry.get("name", "")) == name:
            return entry
    return None


def _field_matches(entry: dict, field: str, expected: object) -> bool:
    actual = entry.get(field)
    if isinstance(expected, bool):
        if isinstance(actual, bool):
            return actual is expected
        if isinstance(actual, int) and actual in {0, 1}:
            return bool(actual) is expected
        if isinstance(actual, str):
            return actual.strip().lower() in (
                {"1", "true", "yes", "enabled"} if expected else {"0", "false", "no", "disabled"}
            )
        return False
    return str(actual) == str(expected)


def _walk_values(value: object, key: str) -> list[object]:
    found: list[object] = []
    if isinstance(value, dict):
        for current_key, current_value in value.items():
            if current_key.lower() == key.lower():
                found.append(current_value)
            found.extend(_walk_values(current_value, key))
    elif isinstance(value, list):
        for item in value:
            found.extend(_walk_values(item, key))
    return found


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


def list_accounts(state_dir: Path | None = None) -> dict:
    url = f"{_splunk_base()}/servicesNS/nobody/Splunk_TA_sim/splunk_infrastructure_monitoring_account?output_mode=json"
    code, body = _splunk_request("GET", url)
    return {"status_code": code, "response": redact(body)}


def preflight() -> dict:
    """Read every Splunk endpoint used by the composed SIM apply."""
    base = _splunk_base()
    endpoints = {
        "indexes": f"{base}/services/data/indexes?output_mode=json&count=0",
        "accounts": (
            f"{base}/servicesNS/nobody/Splunk_TA_sim/"
            "splunk_infrastructure_monitoring_account?output_mode=json&count=0"
        ),
        "modular_inputs": (
            f"{base}/servicesNS/nobody/Splunk_TA_sim/data/inputs/"
            "splunk_infrastructure_monitoring_data_streams?output_mode=json&count=0"
        ),
    }
    statuses: dict[str, int] = {}
    for name, url in endpoints.items():
        code, _ = _splunk_request("GET", url)
        statuses[name] = code
    return {"result": "success", "endpoints": statuses}


def preflight_platform() -> dict:
    """Verify base app/index collections before an optional TA install."""
    base = _splunk_base()
    statuses: dict[str, int] = {}
    for name, url in {
        "apps": f"{base}/services/apps/local?output_mode=json&count=0",
        "indexes": f"{base}/services/data/indexes?output_mode=json&count=0",
    }.items():
        code, _ = _splunk_request("GET", url)
        statuses[name] = code
    return {"result": "success", "endpoints": statuses}


def ensure_metric_index(name: str, state_dir: Path | None = None) -> dict:
    if not name.strip():
        raise ValueError("metrics index name must not be empty")
    base_url = f"{_splunk_base()}/services/data/indexes"
    _, before = _splunk_request("GET", f"{base_url}?output_mode=json&count=0")
    existing = _find_entry(before, name)
    if existing is None:
        code, response = _splunk_request(
            "POST", f"{base_url}?output_mode=json", {"name": name, "datatype": "metric"}
        )
        action = "created"
    else:
        code, response = 200, {"status": "already-present"}
        action = "unchanged"
    _, after = _splunk_request("GET", f"{base_url}?output_mode=json&count=0")
    current = _find_entry(after, name)
    if current is None or not _field_matches(current, "datatype", "metric"):
        raise RuntimeError(f"index {name!r} is absent or is not a metrics index after apply")
    result = "success" if action == "created" else "skipped"
    if state_dir is not None:
        append_step(
            state_dir,
            "sim_addon",
            "ensure_metric_index",
            f"sim_addon:index:{name}",
            result,
            response={"name": name, "datatype": "metric", "action": action},
        )
    return {
        "result": result,
        "status_code": code,
        "action": action,
        "response": redact(response),
    }


def create_account(
    name: str,
    realm: str,
    org_token_file: str,
    job_start_rate: int = 60,
    event_search_rate: int = 30,
    state_dir: Path | None = None,
) -> dict:
    """Create a SIM Add-on account through the UCC REST handler.

    Existing named accounts are updated and then read back; state is never
    trusted as a substitute for live convergence.
    """
    if not name.strip() or realm not in O11Y_API_REALMS:
        raise ValueError(
            f"SIM account name must be non-empty and realm must be one of: {', '.join(sorted(O11Y_API_REALMS))}"
        )
    if job_start_rate <= 0 or event_search_rate <= 0:
        raise ValueError("SIM account polling rates must be positive integers")
    idem = f"sim_addon:account:{name}:{realm}"
    org_token = read_secret_file(org_token_file)
    base_url = f"{_splunk_base()}/servicesNS/nobody/Splunk_TA_sim/splunk_infrastructure_monitoring_account"
    _, before = _splunk_request("GET", f"{base_url}?output_mode=json&count=0")
    existing = _find_entry(before, name)
    payload = {
        "realm": realm,
        "access_token": org_token,
        "job_start_rate": str(job_start_rate),
        "event_search_rate": str(event_search_rate),
    }
    if existing is None:
        payload["name"] = name
        url = base_url
        action = "created"
    else:
        url = f"{base_url}/{urllib.parse.quote(name, safe='')}"
        action = "updated"
    try:
        code, body = _splunk_request("POST", url, payload)
    finally:
        org_token = ""
        payload["access_token"] = ""
    _, after = _splunk_request("GET", f"{base_url}?output_mode=json&count=0")
    current = _find_entry(after, name)
    expected_fields = {
        "realm": realm,
        "job_start_rate": job_start_rate,
        "event_search_rate": event_search_rate,
    }
    mismatched = (
        list(expected_fields)
        if current is None
        else [
            field
            for field, expected in expected_fields.items()
            if not _field_matches(current, field, expected)
        ]
    )
    if mismatched:
        raise RuntimeError(
            f"SIM account {name!r} readback mismatched fields: {', '.join(mismatched)}"
        )
    result = "success"
    if state_dir is not None:
        sanitized = {"name": name, "realm": realm, "status": "configured", "action": action}
        append_step(state_dir, "sim_addon", "create_account", idem, result, response=sanitized)
    return {"result": result, "status_code": code, "action": action}


def check_connection(name: str, state_dir: Path | None = None) -> dict:
    if not name.strip():
        raise ValueError("SIM account name must not be empty")
    url = f"{_splunk_base()}/servicesNS/nobody/Splunk_TA_sim/splunk_infrastructure_monitoring_account/{urllib.parse.quote(name, safe='')}/check_connection"
    code, body = _splunk_request("POST", url, {})
    if any(value is False for value in _walk_values(body, "success")):
        raise RuntimeError(f"SIM account {name!r} connection check returned success=false")
    bad_statuses = {"failed", "failure", "error", "invalid"}
    for value in _walk_values(body, "status"):
        if isinstance(value, str) and value.strip().lower() in bad_statuses:
            raise RuntimeError(
                f"SIM account {name!r} connection check returned status {value!r}"
            )
    for value in _walk_values(body, "error"):
        if value not in (None, "", False, [], {}):
            raise RuntimeError(f"SIM account {name!r} connection check returned an error")
    affirmative = any(
        value is True
        or (isinstance(value, int) and value == 1)
        or (isinstance(value, str) and value.strip().lower() in {"true", "yes", "1"})
        for value in _walk_values(body, "success")
    )
    affirmative_statuses = {"success", "ok", "connected", "valid"}
    affirmative = affirmative or any(
        isinstance(value, str) and value.strip().lower() in affirmative_statuses
        for value in _walk_values(body, "status")
    )
    affirmative = affirmative or any(
        isinstance(value, str)
        and any(word in value.strip().lower() for word in ("success", "connected", "valid"))
        for value in _walk_values(body, "message")
    )
    if not affirmative:
        raise RuntimeError(
            f"SIM account {name!r} connection check returned no affirmative success indicator"
        )
    result = "success" if 200 <= code < 300 else "failed"
    if state_dir is not None:
        append_step(state_dir, "sim_addon", "check_connection", f"sim_addon:check:{name}", result, response=body)
    return {"result": result, "status_code": code, "response": redact(body)}


def enable_account(name: str, enabled: bool, state_dir: Path | None = None) -> dict:
    if not name.strip():
        raise ValueError("SIM account name must not be empty")
    base_url = f"{_splunk_base()}/servicesNS/nobody/Splunk_TA_sim/splunk_infrastructure_monitoring_account"
    url = f"{base_url}/{urllib.parse.quote(name, safe='')}/data_collection"
    code, body = _splunk_request("POST", url, {"enabled": "1" if enabled else "0"})
    _, after = _splunk_request("GET", f"{base_url}?output_mode=json&count=0")
    current = _find_entry(after, name)
    if current is None:
        raise RuntimeError(f"SIM account {name!r} disappeared after data-collection update")
    matching_readback = any(
        (
            field == "disabled" and _field_matches(current, field, not enabled)
        )
        or (
            field != "disabled" and _field_matches(current, field, enabled)
        )
        for field in ("enabled", "data_collection_enabled", "data_collection", "disabled")
        if field in current
    )
    if not matching_readback:
        raise RuntimeError(
            f"SIM account {name!r} data-collection readback did not match enabled={enabled}"
        )
    result = "success"
    if state_dir is not None:
        append_step(state_dir, "sim_addon", "enable_account", f"sim_addon:enable:{name}:{enabled}", result, response=body)
    return {
        "result": result,
        "status_code": code,
        "response": redact(body),
        "readback": redact(current),
    }


def preflight_mts(name: str, mts_per_entity: int, expected_entities: int) -> dict:
    if not name.strip() or mts_per_entity <= 0 or expected_entities <= 0:
        return {
            "result": "failed",
            "reason": "name must be non-empty and MTS/entity estimates must be positive integers.",
        }
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
    if not all(value.strip() for value in (name, index, account, signalflow_program)):
        raise ValueError("modular-input name, index, account, and SignalFlow program must not be empty")
    if interval_seconds <= 0:
        raise ValueError("modular-input interval must be a positive integer")
    if name.upper().startswith("SAMPLE_"):
        return {
            "result": "failed",
            "reason": "Splunk Infrastructure Monitoring Add-on never runs SAMPLE_-prefixed programs; pass a name without the prefix.",
        }
    idem = f"sim_addon:modinput:{name}"
    base_url = f"{_splunk_base()}/servicesNS/nobody/Splunk_TA_sim/data/inputs/splunk_infrastructure_monitoring_data_streams"
    _, before = _splunk_request("GET", f"{base_url}?output_mode=json&count=0")
    existing = _find_entry(before, name)
    payload = {
        "index": index,
        "account": account,
        "interval": str(interval_seconds),
        "disabled": "0" if enabled else "1",
        "signalflow_program": signalflow_program,
    }
    if existing is None:
        payload["name"] = name
        url = base_url
        action = "created"
    else:
        url = f"{base_url}/{urllib.parse.quote(name, safe='')}"
        action = "updated"
    code, body = _splunk_request("POST", url, payload)
    _, after = _splunk_request("GET", f"{base_url}?output_mode=json&count=0")
    current = _find_entry(after, name)
    if current is None:
        raise RuntimeError(f"SIM modular input {name!r} was not present after apply")
    expected_fields = {
        "index": index,
        "account": account,
        "interval": interval_seconds,
        "disabled": not enabled,
        "signalflow_program": signalflow_program,
    }
    mismatched = [
        field
        for field, expected in expected_fields.items()
        if not _field_matches(current, field, expected)
    ]
    if mismatched:
        raise RuntimeError(
            f"SIM modular input {name!r} readback mismatched fields: {', '.join(mismatched)}"
        )
    result = "success"
    if state_dir is not None:
        append_step(
            state_dir,
            "sim_addon",
            "create_modular_input",
            idem,
            result,
            response={"name": name, "status": result, "action": action},
        )
    return {
        "result": result,
        "status_code": code,
        "response": redact(body),
        "action": action,
    }


def list_modular_inputs() -> dict:
    url = f"{_splunk_base()}/servicesNS/nobody/Splunk_TA_sim/data/inputs/splunk_infrastructure_monitoring_data_streams?output_mode=json"
    code, body = _splunk_request("GET", url)
    return {"status_code": code, "response": redact(body)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", default=None)
    sub = parser.add_subparsers(dest="action", required=True)

    sub.add_parser("preflight")
    sub.add_parser("preflight-platform")
    sub.add_parser("list-accounts")

    ensure_index = sub.add_parser("ensure-metric-index")
    ensure_index.add_argument("--name", required=True)

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
    program = modinput.add_mutually_exclusive_group(required=True)
    program.add_argument("--signalflow-program")
    program.add_argument("--signalflow-program-file")
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
        if args.action == "preflight":
            result = preflight()
        elif args.action == "preflight-platform":
            result = preflight_platform()
        elif args.action == "list-accounts":
            result = list_accounts(state_dir=state_dir)
        elif args.action == "ensure-metric-index":
            result = ensure_metric_index(args.name, state_dir=state_dir)
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
            signalflow_program = args.signalflow_program
            if args.signalflow_program_file:
                program_path = Path(args.signalflow_program_file)
                if not program_path.is_file():
                    raise RuntimeError(
                        f"SignalFlow program file is not readable: {program_path}"
                    )
                signalflow_program = program_path.read_text(encoding="utf-8")
            result = create_modular_input(
                name=args.name,
                index=args.index,
                account=args.account,
                signalflow_program=signalflow_program,
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
