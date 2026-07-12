"""Fail-closed loading for small, one-line secret files.

The helper opens through ``O_NOFOLLOW`` and validates the opened descriptor,
not a path-level preflight result, so a symlink or path-swap cannot redirect a
credential read. It deliberately accepts owner-only modes stricter than 0600
(for example 0400) while rejecting group/world access.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path


DEFAULT_MAXIMUM_BYTES = 64 * 1024


class SecureSecretFileError(ValueError):
    """Raised when a secret file cannot be read without weakening guardrails."""


def _fingerprint(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        info.st_nlink,
    )


def read_private_text_file(
    path: str | os.PathLike[str],
    *,
    label: str,
    maximum_bytes: int = DEFAULT_MAXIMUM_BYTES,
) -> str:
    """Read one stable UTF-8 secret line from a private regular file."""

    target = Path(path).expanduser()
    if maximum_bytes < 1:
        raise SecureSecretFileError("maximum secret-file size must be positive")
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "geteuid"):
        raise SecureSecretFileError(
            f"{label} cannot be read safely: this platform lacks O_NOFOLLOW or geteuid"
        )

    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
    try:
        descriptor = os.open(target, flags)
    except OSError as exc:
        raise SecureSecretFileError(
            f"{label} must be a readable, non-symlink regular file: {target}"
        ) from exc

    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise SecureSecretFileError(
                f"{label} must be a single-link regular file: {target}"
            )
        if before.st_uid != os.geteuid():
            raise SecureSecretFileError(
                f"{label} must be owned by the current user: {target}"
            )
        mode = stat.S_IMODE(before.st_mode)
        if mode & 0o077:
            raise SecureSecretFileError(
                f"{label} permissions must be 0600 or stricter: {target} has {mode:04o}"
            )
        if not 1 <= before.st_size <= maximum_bytes:
            raise SecureSecretFileError(
                f"{label} size must be between 1 and {maximum_bytes} bytes: {target}"
            )

        chunks: list[bytes] = []
        remaining = maximum_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 8192))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)

        after = os.fstat(descriptor)
        data = b"".join(chunks)
        if _fingerprint(before) != _fingerprint(after) or len(data) != before.st_size:
            raise SecureSecretFileError(f"{label} changed while it was read: {target}")
    finally:
        os.close(descriptor)

    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise SecureSecretFileError(
            f"{label} must contain UTF-8 text: {target}"
        ) from exc
    if len(lines) != 1 or "\x00" in lines[0]:
        raise SecureSecretFileError(
            f"{label} must contain exactly one non-empty line: {target}"
        )
    value = lines[0].strip()
    if not value:
        raise SecureSecretFileError(f"{label} must contain a non-empty line: {target}")
    return value
