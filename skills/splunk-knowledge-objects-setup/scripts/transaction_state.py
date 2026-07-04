#!/usr/bin/env python3
"""Build sanitized live-status and transaction evidence for knowledge objects.

The network and credential boundary remains in ``setup.sh`` and the shared REST
helpers. This helper parses response snapshots, classifies failure state, and
writes private evidence without placing session keys or object content on a
command line. It never prepares or performs rollback writes.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)

    status = commands.add_parser("status")
    status.add_argument("--object-file", required=True)
    status.add_argument("--object-code", required=True)
    status.add_argument("--acl-file", required=True)
    status.add_argument("--acl-code", required=True)
    status.add_argument("--desired-body-file", required=True)
    status.add_argument("--acl-plan", required=True)
    status.add_argument("--props-file")
    status.add_argument("--props-code", default="not-requested")
    status.add_argument("--props-body-file")
    status.add_argument("--output", required=True)

    classify = commands.add_parser("classify-config")
    classify.add_argument("--before-file", required=True)
    classify.add_argument("--before-code", required=True)
    classify.add_argument("--current-file", required=True)
    classify.add_argument("--current-code", required=True)
    classify.add_argument("--desired-body-file", required=True)

    claim = commands.add_parser("claim-config")
    claim.add_argument("--snapshot", required=True)
    claim.add_argument("--desired-body-file", required=True)

    classify_acl = commands.add_parser("classify-acl")
    classify_acl.add_argument("--before-file", required=True)
    classify_acl.add_argument("--current-file", required=True)
    classify_acl.add_argument("--expected-plan", required=True)

    context = commands.add_parser("context")
    context.add_argument("--snapshot", required=True)

    evidence = commands.add_parser("evidence")
    evidence.add_argument("--events", required=True)
    evidence.add_argument("--output", required=True)
    evidence.add_argument("--result", choices=("succeeded", "failed"), required=True)
    evidence.add_argument("--failure-step", default="")
    evidence.add_argument("--rollback", choices=("not-required", "complete", "partial"), required=True)
    evidence.add_argument("--app", required=True)
    evidence.add_argument("--kind", required=True)
    evidence.add_argument("--name", required=True)
    evidence.add_argument("--object-existed", choices=("true", "false"), required=True)
    evidence.add_argument("--manual-cleanup-required", choices=("true", "false"), required=True)
    evidence.add_argument("--manual-cleanup-path", default="")

    event = commands.add_parser("event")
    event.add_argument("--events", required=True)
    event.add_argument("--step", required=True)
    event.add_argument(
        "--status", choices=("passed", "failed", "unchanged", "refused"), required=True
    )
    event.add_argument("--detail", required=True)

    publish = commands.add_parser("publish")
    publish.add_argument("--source", required=True)
    publish.add_argument("--output", required=True)

    publish_raw = commands.add_parser("publish-raw")
    publish_raw.add_argument("--source", required=True)
    publish_raw.add_argument("--output", required=True)
    return root


def load_json(path: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"ERROR: invalid Splunk JSON snapshot: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit("ERROR: Splunk JSON snapshot must be an object.")
    return value


def entry_from(path: str) -> dict[str, Any]:
    payload = load_json(path)
    entries = payload.get("entry", [])
    if not isinstance(entries, list) or not entries or not isinstance(entries[0], dict):
        raise SystemExit("ERROR: Splunk JSON snapshot has no entry.")
    return entries[0]


def content_from(path: str) -> dict[str, Any]:
    content = entry_from(path).get("content", {})
    if not isinstance(content, dict):
        raise SystemExit("ERROR: Splunk JSON entry content is not an object.")
    return content


def scalar(value: Any) -> str:
    if value is True:
        return "1"
    if value is False:
        return "0"
    if value is None:
        return ""
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    return str(value)


def desired_pairs(path: str) -> list[tuple[str, str]]:
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"ERROR: could not read desired form body: {exc}") from exc
    return parse_qsl(raw, keep_blank_values=True)


def acl_from(path: str) -> dict[str, Any]:
    entry = entry_from(path)
    content = entry.get("content", {})
    acl = entry.get("acl", {})
    if not isinstance(content, dict):
        content = {}
    if not isinstance(acl, dict):
        acl = {}
    embedded = content.get("eai:acl", {})
    if isinstance(embedded, dict):
        acl = {**embedded, **acl}
    # The dedicated /acl endpoint returns owner/sharing/perms in content on
    # some Splunk releases and entry.acl on others.
    merged = {**acl, **content}
    permissions = merged.get("perms", {})
    if not isinstance(permissions, dict):
        permissions = {}

    def roles(name: str) -> list[str]:
        value = merged.get(f"perms.{name}", permissions.get(name, []))
        if isinstance(value, str):
            return sorted(item.strip() for item in value.split(",") if item.strip())
        if isinstance(value, list):
            return sorted(str(item).strip() for item in value if str(item).strip())
        return []

    return {
        "owner": scalar(merged.get("owner", "")),
        "sharing": scalar(merged.get("sharing", "")),
        "read_roles": roles("read"),
        "write_roles": roles("write"),
    }


def private_atomic_bytes(path_value: str, content: bytes) -> None:
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise SystemExit(f"ERROR: refusing symlink evidence target: {path}")
    parent_mode = stat.S_IMODE(path.parent.stat().st_mode)
    if parent_mode & 0o077:
        path.parent.chmod(parent_mode & ~0o077)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        os.chmod(path, 0o600)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def private_atomic_json(path_value: str, payload: dict[str, Any]) -> None:
    content = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    private_atomic_bytes(path_value, content)


def value_matches(actual: dict[str, Any], key: str, expected: str) -> bool:
    # Splunk can omit an empty conf field instead of returning it as an empty
    # string, so those two representations are equivalent for rollback/status.
    return scalar(actual.get(key, "")) == expected


def command_status(args: argparse.Namespace) -> int:
    object_ok = args.object_code == "200"
    acl_ok = args.acl_code == "200"
    checks: list[dict[str, Any]] = []
    if object_ok:
        content = content_from(args.object_file)
        for key, expected in desired_pairs(args.desired_body_file):
            checks.append({"field": key, "matches": value_matches(content, key, expected)})

    plan = load_json(args.acl_plan)
    expected_acl = {
        "owner": scalar(plan.get("owner", "")),
        "sharing": scalar(plan.get("sharing", "")),
        "read_roles": sorted(str(item) for item in plan.get("read_roles", [])),
        "write_roles": sorted(str(item) for item in plan.get("write_roles", [])),
    }
    actual_acl: dict[str, Any] = {}
    acl_matches = False
    if acl_ok:
        actual_acl = acl_from(args.acl_file)
        acl_matches = actual_acl == expected_acl

    props_requested = bool(args.props_file and args.props_body_file)
    props_checks: list[dict[str, Any]] = []
    props_ok = not props_requested
    if props_requested and args.props_code == "200":
        props_content = content_from(args.props_file)
        for key, expected in desired_pairs(args.props_body_file):
            props_checks.append({"field": key, "matches": value_matches(props_content, key, expected)})
        props_ok = all(item["matches"] for item in props_checks)

    matched = (
        object_ok
        and acl_ok
        and bool(checks)
        and all(item["matches"] for item in checks)
        and acl_matches
        and props_ok
    )
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "live_query": True,
        "match": matched,
        "object": {
            "http_code": args.object_code,
            "exists": object_ok,
            "field_checks": checks,
        },
        "acl": {
            "http_code": args.acl_code,
            "matches": acl_matches,
            "expected": expected_acl,
            "actual": actual_acl,
        },
        "automatic_lookup": {
            "requested": props_requested,
            "http_code": args.props_code,
            "matches": props_ok,
            "field_checks": props_checks,
        },
    }
    private_atomic_json(args.output, payload)
    return 0 if matched else 1


def command_classify_config(args: argparse.Namespace) -> int:
    if args.before_code == "404":
        if args.current_code == "404":
            print("unchanged")
            return 0
        # Whole-stanza deletion is intentionally unsupported: the live state
        # can change after this read and Splunk exposes no conditional DELETE.
        print("conflict")
        return 0

    if args.before_code != "200" or args.current_code != "200":
        print("conflict")
        return 0
    before = content_from(args.before_file)
    current = content_from(args.current_file)
    needs_restore = False
    for key, desired in desired_pairs(args.desired_body_file):
        old = scalar(before.get(key, ""))
        now = scalar(current.get(key, ""))
        if now == old:
            continue
        if now == desired:
            needs_restore = True
            continue
        print("conflict")
        return 0
    print("restore" if needs_restore else "unchanged")
    return 0


def mutable_content(content: dict[str, Any]) -> dict[str, str]:
    """Return only stanza fields an actor can alter.

    Splunk can update ``eai:*`` metadata when ACL ownership changes, so those
    server-owned fields are deliberately excluded. Every other content field
    is compared; an unexpected field therefore blocks destructive rollback.
    """

    return {
        str(key): scalar(value)
        for key, value in content.items()
        if not str(key).startswith("eai:")
    }


def expected_content(path: str) -> dict[str, str]:
    return {key: value for key, value in desired_pairs(path)}


def command_claim_config(args: argparse.Namespace) -> int:
    current = mutable_content(content_from(args.snapshot))
    expected = expected_content(args.desired_body_file)
    if current != expected:
        unexpected = sorted(set(current) - set(expected))
        missing = sorted(set(expected) - set(current))
        mismatched = sorted(
            key for key in set(current) & set(expected) if current[key] != expected[key]
        )
        detail = {
            "unexpected_fields": unexpected,
            "missing_fields": missing,
            "mismatched_fields": mismatched,
        }
        print(json.dumps(detail, sort_keys=True))
        return 1
    return 0


def command_classify_acl(args: argparse.Namespace) -> int:
    before = acl_from(args.before_file)
    current = acl_from(args.current_file)
    plan = load_json(args.expected_plan)
    expected = {
        "owner": scalar(plan.get("owner", "")),
        "sharing": scalar(plan.get("sharing", "")),
        "read_roles": sorted(str(item) for item in plan.get("read_roles", [])),
        "write_roles": sorted(str(item) for item in plan.get("write_roles", [])),
    }
    needs_restore = False
    for key in ("owner", "sharing", "read_roles", "write_roles"):
        if current[key] == before[key]:
            continue
        if current[key] == expected[key]:
            needs_restore = True
            continue
        print("conflict")
        return 0
    print("restore" if needs_restore else "unchanged")
    return 0


def command_context(args: argparse.Namespace) -> int:
    entry = entry_from(args.snapshot)
    content = entry.get("content", {})
    if not isinstance(content, dict):
        raise SystemExit("ERROR: current-context content is invalid.")
    username = scalar(content.get("username", entry.get("name", "")))
    capabilities = content.get("capabilities", [])
    if not username or not isinstance(capabilities, list):
        raise SystemExit("ERROR: current-context did not include username/capabilities.")
    print(json.dumps({"username": username, "capabilities": sorted(map(str, capabilities))}))
    return 0


def command_event(args: argparse.Namespace) -> int:
    path = Path(args.events)
    if path.is_symlink():
        raise SystemExit(f"ERROR: refusing symlink event log: {path}")
    record = {
        "at": datetime.now(timezone.utc).isoformat(),
        "step": args.step,
        "status": args.status,
        "detail": args.detail,
    }
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, (json.dumps(record, sort_keys=True) + "\n").encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    return 0


def command_evidence(args: argparse.Namespace) -> int:
    events: list[dict[str, Any]] = []
    try:
        lines = Path(args.events).read_text(encoding="utf-8").splitlines()
        for line in lines:
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError("event is not an object")
            events.append(item)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"ERROR: invalid transaction event log: {exc}") from exc
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "transactional_apply": True,
        "target": {"app": args.app, "kind": args.kind, "name": args.name},
        "prestate": {"object_existed": args.object_existed == "true"},
        "result": args.result,
        "failure_step": args.failure_step or None,
        "rollback": args.rollback,
        "partial_failure": args.rollback == "partial",
        "manual_cleanup_required": args.manual_cleanup_required == "true",
        "manual_cleanup_path": args.manual_cleanup_path or None,
        "manual_cleanup_guidance": (
            "Review the private before/current snapshots, fetch the exact live stanza and ACL again, "
            "confirm no concurrent owner changed them, then reconcile through the supported Splunk UI/REST workflow. "
            "Automatic restore POST and DELETE are intentionally disabled."
            if args.manual_cleanup_required == "true"
            else None
        ),
        "events": events,
    }
    private_atomic_json(args.output, payload)
    return 0


def command_publish(args: argparse.Namespace) -> int:
    private_atomic_json(args.output, load_json(args.source))
    return 0


def command_publish_raw(args: argparse.Namespace) -> int:
    try:
        content = Path(args.source).read_bytes()
    except OSError as exc:
        raise SystemExit(f"ERROR: could not read private snapshot: {exc}") from exc
    if len(content) > 16 * 1024 * 1024:
        raise SystemExit("ERROR: private snapshot exceeds the 16 MiB evidence limit.")
    private_atomic_bytes(args.output, content)
    return 0


def main() -> int:
    args = parser().parse_args()
    commands = {
        "status": command_status,
        "classify-config": command_classify_config,
        "claim-config": command_claim_config,
        "classify-acl": command_classify_acl,
        "context": command_context,
        "event": command_event,
        "evidence": command_evidence,
        "publish": command_publish,
        "publish-raw": command_publish_raw,
    }
    return commands[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
