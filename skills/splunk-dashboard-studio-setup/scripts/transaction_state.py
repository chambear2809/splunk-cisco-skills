#!/usr/bin/env python3
"""Private state, drift, and failure-reconciliation helpers for dashboards."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_json(path: str | Path) -> Any:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def one_entry(path: str | Path) -> dict[str, Any]:
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise ValueError("REST response is not a JSON object")
    entries = payload.get("entry")
    if not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict):
        raise ValueError("REST response does not contain exactly one entry")
    return entries[0]


def scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, list):
        return scalar(value[-1]) if value else ""
    return str(value)


def string_list(value: Any) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    normalized: set[str] = set()
    for item in values:
        normalized.update(part.strip() for part in str(item).split(",") if part.strip())
    return sorted(normalized)


def csv_roles(value: str) -> list[str]:
    """Normalize a requested comma-separated role set for exact comparison."""

    return sorted({item.strip() for item in value.split(",") if item.strip()})


def view_data(path: str | Path) -> str:
    content = one_entry(path).get("content")
    if not isinstance(content, dict):
        raise ValueError("view entry has no content object")
    value = content.get("eai:data")
    if not isinstance(value, str):
        raise ValueError("view entry has no string eai:data field")
    return value


def acl_data(path: str | Path) -> dict[str, Any]:
    entry = one_entry(path)
    content = entry.get("content")
    candidates: list[Any] = [entry.get("acl")]
    if isinstance(content, dict):
        candidates.extend((content.get("eai:acl"), content))
    acl = next(
        (
            candidate
            for candidate in candidates
            if isinstance(candidate, dict)
            and "owner" in candidate
            and "sharing" in candidate
        ),
        None,
    )
    if acl is None:
        raise ValueError("ACL response has no owner/sharing object")
    perms = acl.get("perms")
    if not isinstance(perms, dict):
        perms = {}
    return {
        "owner": scalar(acl.get("owner")),
        "sharing": scalar(acl.get("sharing")),
        "read": string_list(perms.get("read")),
        "write": string_list(perms.get("write")),
    }


def private_atomic_json(path: str | Path, payload: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(destination.parent, 0o700)
    if destination.is_symlink():
        raise ValueError(f"refusing symlink state file: {destination}")
    fd, temporary = tempfile.mkstemp(prefix=".state.", dir=destination.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def private_atomic_bytes(path: str | Path, payload: bytes) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(destination.parent, 0o700)
    if destination.is_symlink():
        raise ValueError(f"refusing symlink state file: {destination}")
    fd, temporary = tempfile.mkstemp(prefix=".state.", dir=destination.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def command_snapshot_valid(args: argparse.Namespace) -> int:
    view_data(args.view)
    acl_data(args.acl)
    return 0


def command_view_matches(args: argparse.Namespace) -> int:
    desired = Path(args.desired_view).read_text(encoding="utf-8")
    return 0 if view_data(args.view) == desired else 1


def command_json_valid(args: argparse.Namespace) -> int:
    payload = load_json(args.path)
    if not isinstance(payload, dict) or not isinstance(payload.get("entry"), list):
        return 1
    if args.one_entry and (
        len(payload["entry"]) != 1 or not isinstance(payload["entry"][0], dict)
    ):
        return 1
    return 0


def command_status(args: argparse.Namespace) -> int:
    desired = Path(args.desired_view).read_text(encoding="utf-8")
    actual = ""
    actual_acl: dict[str, Any] = {}
    view_valid = args.view_code == "200"
    acl_valid = args.acl_code == "200"
    if view_valid:
        try:
            actual = view_data(args.view)
        except (OSError, ValueError, json.JSONDecodeError):
            view_valid = False
    if acl_valid:
        try:
            actual_acl = acl_data(args.acl)
        except (OSError, ValueError, json.JSONDecodeError):
            acl_valid = False

    content_matches = view_valid and actual == desired
    owner_matches = acl_valid and actual_acl.get("owner") == args.owner
    sharing_matches = acl_valid and actual_acl.get("sharing") == args.sharing
    expected_read = csv_roles(args.read_roles)
    expected_write = csv_roles(args.write_roles)
    read_roles_match = acl_valid and actual_acl.get("read") == expected_read
    write_roles_match = acl_valid and actual_acl.get("write") == expected_write
    matched = (
        content_matches
        and owner_matches
        and sharing_matches
        and read_roles_match
        and write_roles_match
    )
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "live_query": True,
        "match": matched,
        "target": {"app": args.app, "dashboard": args.name},
        "view": {
            "http_code": args.view_code,
            "exists": args.view_code == "200",
            "response_valid": view_valid,
            "content_matches": content_matches,
            "desired_sha256": digest(desired),
            "actual_sha256": digest(actual) if view_valid else None,
        },
        "acl": {
            "http_code": args.acl_code,
            "response_valid": acl_valid,
            "owner_matches": owner_matches,
            "sharing_matches": sharing_matches,
            "read_roles_match": read_roles_match,
            "write_roles_match": write_roles_match,
            "expected": {
                "owner": args.owner,
                "sharing": args.sharing,
                "read": expected_read,
                "write": expected_write,
            },
            "actual": {
                "owner": actual_acl.get("owner"),
                "sharing": actual_acl.get("sharing"),
                "read": actual_acl.get("read"),
                "write": actual_acl.get("write"),
            }
            if acl_valid
            else {},
        },
    }
    private_atomic_json(args.output, payload)
    return 0 if matched else 1


def command_compare_snapshots(args: argparse.Namespace) -> int:
    try:
        matches = (
            view_data(args.expected_view) == view_data(args.actual_view)
            and acl_data(args.expected_acl) == acl_data(args.actual_acl)
        )
    except (OSError, ValueError, json.JSONDecodeError):
        return 1
    return 0 if matches else 1


def read_events(path: str | Path) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    event_path = Path(path)
    if not event_path.exists():
        return events
    with event_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            raw = json.loads(line)
            if not isinstance(raw, dict):
                continue
            events.append(
                {
                    "step": scalar(raw.get("step")),
                    "status": scalar(raw.get("status")),
                    "detail": scalar(raw.get("detail")),
                }
            )
    return events


def command_event(args: argparse.Namespace) -> int:
    event = {"step": args.step, "status": args.status, "detail": args.detail}
    path = Path(args.events)
    if path.is_symlink():
        raise ValueError(f"refusing symlink event file: {path}")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
    os.chmod(path, 0o600)
    return 0


def command_evidence(args: argparse.Namespace) -> int:
    events = read_events(args.events)
    manual_cleanup_required = args.manual_cleanup_required == "true" or any(
        event["status"] == "manual-cleanup-required" for event in events
    )
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "result": args.result,
        "failure_step": args.failure_step or None,
        "rollback": args.rollback,
        "partial_failure": args.rollback == "partial",
        "target": {"app": args.app, "dashboard": args.name},
        "object_existed_before": args.object_existed == "true",
        "redacted": True,
        "concurrent_or_unverifiable": any(
            event["status"] in {"refused", "manual-cleanup-required"}
            for event in events
        ),
        "manual_cleanup": {
            "required": manual_cleanup_required,
            "private_snapshot_path": args.manual_cleanup_path or None,
            "guidance": (
                "Review the private before/current snapshots, fetch the exact live view and "
                "ACL again, confirm no concurrent owner changed them, then reconcile through "
                "the supported Splunk UI/REST workflow. Automatic restore POST and DELETE are disabled."
                if manual_cleanup_required
                else None
            ),
        },
        "events": events,
    }
    private_atomic_json(args.output, payload)
    return 0


def command_publish_raw(args: argparse.Namespace) -> int:
    try:
        payload = Path(args.source).read_bytes()
    except OSError as exc:
        raise ValueError(f"could not read private snapshot: {exc}") from exc
    if len(payload) > 16 * 1024 * 1024:
        raise ValueError("private snapshot exceeds the 16 MiB evidence limit")
    private_atomic_bytes(args.output, payload)
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)

    snapshot = commands.add_parser("snapshot-valid")
    snapshot.add_argument("--view", required=True)
    snapshot.add_argument("--acl", required=True)
    snapshot.set_defaults(func=command_snapshot_valid)

    view_matches = commands.add_parser("view-matches")
    view_matches.add_argument("--view", required=True)
    view_matches.add_argument("--desired-view", required=True)
    view_matches.set_defaults(func=command_view_matches)

    valid = commands.add_parser("json-valid")
    valid.add_argument("--path", required=True)
    valid.add_argument("--one-entry", action="store_true")
    valid.set_defaults(func=command_json_valid)

    status = commands.add_parser("status")
    status.add_argument("--view", required=True)
    status.add_argument("--view-code", required=True)
    status.add_argument("--acl", required=True)
    status.add_argument("--acl-code", required=True)
    status.add_argument("--desired-view", required=True)
    status.add_argument("--owner", required=True)
    status.add_argument("--sharing", required=True)
    status.add_argument("--read-roles", default="*")
    status.add_argument("--write-roles", default="")
    status.add_argument("--app", required=True)
    status.add_argument("--name", required=True)
    status.add_argument("--output", required=True)
    status.set_defaults(func=command_status)

    compare = commands.add_parser("compare-snapshots")
    compare.add_argument("--expected-view", required=True)
    compare.add_argument("--expected-acl", required=True)
    compare.add_argument("--actual-view", required=True)
    compare.add_argument("--actual-acl", required=True)
    compare.set_defaults(func=command_compare_snapshots)

    event = commands.add_parser("event")
    event.add_argument("--events", required=True)
    event.add_argument("--step", required=True)
    event.add_argument("--status", required=True)
    event.add_argument("--detail", required=True)
    event.set_defaults(func=command_event)

    evidence = commands.add_parser("evidence")
    evidence.add_argument("--events", required=True)
    evidence.add_argument("--output", required=True)
    evidence.add_argument("--result", required=True)
    evidence.add_argument("--failure-step", default="")
    evidence.add_argument("--rollback", required=True)
    evidence.add_argument("--app", required=True)
    evidence.add_argument("--name", required=True)
    evidence.add_argument("--object-existed", choices=("true", "false"), required=True)
    evidence.add_argument(
        "--manual-cleanup-required", choices=("true", "false"), required=True
    )
    evidence.add_argument("--manual-cleanup-path", default="")
    evidence.set_defaults(func=command_evidence)

    publish_raw = commands.add_parser("publish-raw")
    publish_raw.add_argument("--source", required=True)
    publish_raw.add_argument("--output", required=True)
    publish_raw.set_defaults(func=command_publish_raw)
    return root


def main() -> int:
    args = parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
