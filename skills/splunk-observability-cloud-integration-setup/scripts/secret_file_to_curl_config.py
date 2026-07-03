#!/usr/bin/env python3
"""Convert one validated secret-file value into a private curl config field."""

from __future__ import annotations

import argparse
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

from _apply_state import read_secret_file

SAFE_FIELD_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _curl_config_escape(value: str) -> str:
    if not value or any(not character.isprintable() for character in value):
        raise ValueError("secret contains a control character unsupported by curl config")
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _write_private_config(output: Path, payload: str) -> None:
    parent = output.parent
    try:
        parent_info = parent.lstat()
    except OSError as exc:
        raise PermissionError(f"curl config parent is missing or unreadable: {parent}") from exc
    if stat.S_ISLNK(parent_info.st_mode) or not stat.S_ISDIR(parent_info.st_mode):
        raise PermissionError("curl config parent must be a non-symlink directory")

    descriptor, temporary_name = tempfile.mkstemp(dir=parent, prefix=".curl-secret-config.")
    temporary: Path | None = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or stat.S_IMODE(opened.st_mode) != 0o600
        ):
            raise PermissionError("private curl config temporary file failed validation")
        with os.fdopen(descriptor, "w", encoding="utf-8") as destination:
            descriptor = -1
            destination.write(payload)
            destination.flush()
            os.fsync(destination.fileno())
        written = temporary.lstat()
        if (
            not stat.S_ISREG(written.st_mode)
            or written.st_nlink != 1
            or stat.S_IMODE(written.st_mode) != 0o600
        ):
            raise PermissionError("private curl config temporary file changed while writing")
        os.replace(temporary, output)
        temporary = None
        final = output.lstat()
        if (
            not stat.S_ISREG(final.st_mode)
            or final.st_nlink != 1
            or stat.S_IMODE(final.st_mode) != 0o600
        ):
            raise PermissionError("private curl config failed final validation")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_config(field: str, secret_file: Path, output: Path) -> None:
    if not SAFE_FIELD_RE.fullmatch(field):
        raise ValueError("curl form field contains unsupported characters")
    secret = read_secret_file(secret_file, allow_unicode_printable=True)
    payload = f'data-urlencode = "{field}={_curl_config_escape(secret)}"\n'
    _write_private_config(output, payload)


def write_basic_auth_config(output: Path) -> None:
    try:
        username = os.environ["SPLUNK_USER"]
        password = os.environ["SPLUNK_PASS"]
    except KeyError as exc:
        raise ValueError(f"{exc.args[0]} must be set in the environment") from exc
    payload = (
        f'user = "{_curl_config_escape(username)}:'
        f'{_curl_config_escape(password)}"\n'
    )
    _write_private_config(output, payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--field")
    mode.add_argument("--basic-auth-env", action="store_true")
    parser.add_argument("--secret-file", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.basic_auth_env:
            if args.secret_file is not None:
                raise ValueError("--secret-file is invalid with --basic-auth-env")
            write_basic_auth_config(args.output)
        else:
            if args.secret_file is None:
                raise ValueError("--secret-file is required with --field")
            write_config(args.field, args.secret_file, args.output)
    except (OSError, PermissionError, UnicodeError, ValueError) as exc:
        print(f"secret_file_to_curl_config FAILED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
