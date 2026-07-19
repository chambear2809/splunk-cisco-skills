#!/usr/bin/env python3
"""Validate and transactionally cut over the Collector's Splunk token file.

The command never accepts a secret value. ``apply`` compares two root-owned
0600 environment files and permits exactly one change: the value assigned to
``SPLUNK_ACCESS_TOKEN``. It then delegates the crash-durable file, service, and
health transaction to ``transactional_apply.py`` with live-hash and private-
artifact gates enabled. ``restore`` delegates exact-manifest rollback.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Sequence


TRANSACTION_HELPER = Path(__file__).with_name("transactional_apply.py")
TOKEN_KEY = "SPLUNK_ACCESS_TOKEN"
MAX_ENVIRONMENT_BYTES = 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9._~+/=-]{16,8192}$")


class CutoverError(ValueError):
    """A sanitized token-cutover preflight failure."""


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # noqa: ARG002
        raise CutoverError("command arguments are invalid")


def emit_error(message: str) -> None:
    sys.stderr.write(
        json.dumps(
            {"error": "splunk_token_cutover_preflight_failed", "message": message},
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


def absolute_path(value: str, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise CutoverError(f"{label} must be an absolute path")
    return path


def validate_sha256(value: str, label: str) -> str:
    if not SHA256_RE.fullmatch(value):
        raise CutoverError(f"{label} must be a SHA-256 value")
    return value.lower()


def _fingerprint(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_gid,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        info.st_nlink,
    )


def assert_secure_ancestry(path: Path, label: str) -> None:
    current = Path("/")
    for component in path.parent.parts[1:]:
        current /= component
        try:
            info = os.lstat(current)
        except OSError as exc:
            raise CutoverError(f"{label} ancestry cannot be inspected") from exc
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != 0
            or stat.S_IMODE(info.st_mode) & 0o022
        ):
            raise CutoverError(
                f"{label} ancestry must be root-owned and not group/other-writable"
            )


def read_private_environment(path: Path, label: str) -> bytes:
    assert_secure_ancestry(path, label)
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
    if not hasattr(os, "O_NOFOLLOW"):
        raise CutoverError("this platform lacks O_NOFOLLOW")
    flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise CutoverError(f"{label} must be a readable non-symlink file") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != 0
            or before.st_gid != 0
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_nlink != 1
            or not 1 <= before.st_size <= MAX_ENVIRONMENT_BYTES
        ):
            raise CutoverError(
                f"{label} must be a root-owned, root-group, single-link regular "
                "file with mode 0600 and bounded size"
            )
        chunks: list[bytes] = []
        remaining = MAX_ENVIRONMENT_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 8192))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    payload = b"".join(chunks)
    if _fingerprint(before) != _fingerprint(after) or len(payload) != before.st_size:
        raise CutoverError(f"{label} changed while it was read")
    return payload


def _token_value_and_redacted(payload: bytes, label: str) -> tuple[str, str, bytes]:
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise CutoverError(f"{label} must contain UTF-8 text") from exc
    if "\x00" in text:
        raise CutoverError(f"{label} contains a forbidden control character")

    matches: list[tuple[int, str, str]] = []
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        body = line.rstrip("\r\n")
        ending = line[len(body) :]
        if body.startswith(f"{TOKEN_KEY}="):
            matches.append((index, body.partition("=")[2], ending))
    if len(matches) != 1:
        raise CutoverError(f"{label} must assign {TOKEN_KEY} exactly once")

    index, raw_value, ending = matches[0]
    style = "unquoted"
    value = raw_value
    if raw_value[:1] in {'"', "'"}:
        if len(raw_value) < 2 or raw_value[-1] != raw_value[0]:
            raise CutoverError(f"{label} has an invalid token quoting style")
        style = "double" if raw_value[0] == '"' else "single"
        value = raw_value[1:-1]
    if not TOKEN_RE.fullmatch(value):
        raise CutoverError(
            f"{label} token must be bounded printable ASCII without whitespace"
        )
    lines[index] = f"{TOKEN_KEY}=<REDACTED>{ending}"
    return value, style, "".join(lines).encode("utf-8")


def validate_cutover_payloads(staged: bytes, live: bytes) -> None:
    staged_token, staged_style, staged_redacted = _token_value_and_redacted(
        staged, "staged environment"
    )
    live_token, live_style, live_redacted = _token_value_and_redacted(
        live, "live environment"
    )
    if staged_style != live_style or not hmac.compare_digest(
        staged_redacted, live_redacted
    ):
        raise CutoverError(
            f"the staged environment may change only {TOKEN_KEY}'s value"
        )
    if hmac.compare_digest(staged_token, live_token):
        raise CutoverError("the staged Splunk token must differ from the live token")


def transaction_apply_argv(args: argparse.Namespace, *, live_sha256: str) -> list[str]:
    return [
        sys.executable,
        str(TRANSACTION_HELPER),
        "apply",
        "--staged",
        args.staged,
        "--live",
        args.live,
        "--service",
        args.service,
        "--health-url",
        args.health_url,
        "--expected-sha256",
        args.expected_sha256,
        "--expected-live-sha256",
        live_sha256,
        "--private-artifact",
        "--collector-binary",
        args.collector_binary,
        "--collector-binary-sha256",
        args.collector_binary_sha256,
        "--state-root",
        args.state_root,
        "--health-timeout",
        str(args.health_timeout),
    ]


def exec_transaction(argv: list[str]) -> None:
    try:
        os.execv(sys.executable, argv)
    except OSError as exc:
        raise CutoverError("transaction helper could not be executed") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = SafeArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    apply_parser = subparsers.add_parser("apply")
    for option in (
        "staged",
        "live",
        "service",
        "health-url",
        "expected-sha256",
        "collector-binary",
        "collector-binary-sha256",
        "state-root",
    ):
        apply_parser.add_argument(f"--{option}", required=True)
    apply_parser.add_argument("--health-timeout", type=float, default=15.0)
    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("--manifest", required=True)
    return parser


def run(args: argparse.Namespace) -> None:
    if not sys.platform.startswith("linux") or os.geteuid() != 0:
        raise CutoverError("token cutover requires root on Linux")
    if args.operation == "restore":
        manifest = absolute_path(args.manifest, "manifest")
        exec_transaction(
            [
                sys.executable,
                str(TRANSACTION_HELPER),
                "restore",
                "--manifest",
                str(manifest),
            ]
        )
        return

    staged_path = absolute_path(args.staged, "staged environment")
    live_path = absolute_path(args.live, "live environment")
    if staged_path == live_path:
        raise CutoverError("staged and live environment paths must differ")
    expected = validate_sha256(args.expected_sha256, "staged expected hash")
    validate_sha256(args.collector_binary_sha256, "collector binary hash")
    staged = read_private_environment(staged_path, "staged environment")
    live = read_private_environment(live_path, "live environment")
    if not hmac.compare_digest(hashlib.sha256(staged).hexdigest(), expected):
        raise CutoverError("staged environment SHA-256 does not match")
    validate_cutover_payloads(staged, live)
    live_sha256 = hashlib.sha256(live).hexdigest()
    exec_transaction(transaction_apply_argv(args, live_sha256=live_sha256))


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        run(args)
    except CutoverError as exc:
        emit_error(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
