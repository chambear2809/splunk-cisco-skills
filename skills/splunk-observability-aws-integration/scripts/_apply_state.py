"""Shared apply-state.json helpers for the Splunk Observability AWS integration API client.

The renderer creates ``state/apply-state.json`` and ``state/idempotency-keys.json``
under the rendered output directory. Each API client appends a step record with
``timestamp``, ``section``, ``step``, ``idempotency_key``, ``result``
(``success | skipped | failed``), and a sanitized response body. Records never
contain a token, password, AWS access key, or external ID (the redactor strips
those).

This module is intentionally dependency-free so it works under the repo's
default Python 3.11 interpreter without installing anything.
"""

from __future__ import annotations

import json
import hashlib
import hmac
import os
import re
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REDACTORS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(authorization|x-sf-token|aws[-_]secret[-_]access[-_]key)\s*[:=]\s*[^\s,'\"]+"),
    re.compile(r"eyJ[A-Za-z0-9._-]{20,}"),
    re.compile(r"(?i)(password|secret|api[_-]?key|token|external[_-]?id)\s*[:=]\s*[^\s,'\"]+"),
)

REDACT_PLACEHOLDER = "[REDACTED]"
MAX_SECRET_BYTES = 64 * 1024
MAX_STATE_BYTES = 4 * 1024 * 1024


def _secure_state_dir(state_dir: Path, *, create: bool) -> bool:
    if state_dir.is_symlink():
        raise PermissionError(f"state directory must not be a symlink: {state_dir}")
    if not state_dir.exists():
        if not create:
            return False
        state_dir.mkdir(parents=True, mode=0o700)
    metadata = state_dir.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise PermissionError(f"state directory must be a regular directory: {state_dir}")
    if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
        raise PermissionError(f"state directory must be owned by the current user: {state_dir}")
    os.chmod(state_dir, 0o700)
    return True


def _validate_state_metadata(state_path: Path, metadata: os.stat_result) -> None:
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_size > MAX_STATE_BYTES
    ):
        raise PermissionError(f"apply state must be a single-hardlink mode-0600 regular file: {state_path}")
    if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
        raise PermissionError(f"apply state must be owned by the current user: {state_path}")


def _validate_state_file(state_path: Path) -> None:
    """Validate path metadata without following a symlink.

    Callers that consume state use :func:`_read_state_bytes`, which repeats
    these checks on the opened descriptor and verifies that the path and
    descriptor still identify the same stable file.
    """
    _validate_state_metadata(state_path, state_path.lstat())


def _state_stat_fingerprint(metadata: os.stat_result) -> tuple[int, ...]:
    """Return metadata that must remain stable for the complete state read."""
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _read_state_from_descriptor(descriptor: int, state_path: Path) -> bytes:
    """Read at most ``MAX_STATE_BYTES`` plus one sentinel byte."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(descriptor, min(64 * 1024, MAX_STATE_BYTES + 1 - total))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
        if total > MAX_STATE_BYTES:
            raise PermissionError(
                f"apply state exceeds the {MAX_STATE_BYTES}-byte safety limit: {state_path}"
            )


def _read_state_bytes(state_path: Path) -> bytes:
    """Read a stable state file through one no-follow descriptor."""
    if not hasattr(os, "O_NOFOLLOW"):
        raise PermissionError("platform lacks O_NOFOLLOW; cannot open apply state safely")
    try:
        path_before = state_path.lstat()
    except OSError as exc:
        raise PermissionError(f"apply state is missing or unreadable: {state_path}") from exc
    _validate_state_metadata(state_path, path_before)

    descriptor: int | None = None
    try:
        descriptor = os.open(
            state_path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW,
        )
        opened_before = os.fstat(descriptor)
        _validate_state_metadata(state_path, opened_before)
        expected = _state_stat_fingerprint(opened_before)
        if _state_stat_fingerprint(path_before) != expected:
            raise PermissionError(f"apply state changed while it was being opened: {state_path}")

        first = _read_state_from_descriptor(descriptor, state_path)
        after_first = os.fstat(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        second = _read_state_from_descriptor(descriptor, state_path)
        opened_after = os.fstat(descriptor)
        path_after = state_path.lstat()
        if any(
            _state_stat_fingerprint(current) != expected
            for current in (after_first, opened_after, path_after)
        ):
            raise PermissionError(f"apply state changed while it was being read: {state_path}")
        if not hmac.compare_digest(
            hashlib.sha256(first).digest(), hashlib.sha256(second).digest()
        ):
            raise PermissionError(f"apply state content changed while it was being read: {state_path}")
        return second
    except PermissionError:
        raise
    except OSError as exc:
        raise PermissionError(f"apply state could not be opened safely: {state_path}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _load_state(state_path: Path) -> dict[str, Any]:
    """Load and validate state, failing closed on corruption or path races."""
    try:
        state = json.loads(_read_state_bytes(state_path).decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot trust invalid apply state {state_path}: {exc}") from exc
    if not isinstance(state, dict) or not isinstance(state.get("steps"), list):
        raise ValueError(f"cannot trust malformed apply state {state_path}")
    if any(not isinstance(entry, dict) for entry in state["steps"]):
        raise ValueError(f"cannot trust malformed apply state {state_path}")
    return state


def redact(value: Any) -> Any:
    """Walk a value and replace anything that looks like a secret."""
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if _looks_secret_key(k) else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        for pat in REDACTORS:
            value = pat.sub(REDACT_PLACEHOLDER, value)
        return value
    return value


def _looks_secret_key(key: str) -> bool:
    canonical = re.sub(r"[^a-z0-9]", "", key.lower())
    return any(s in canonical for s in (
        "token", "password", "secret", "apikey", "jwt",
        "authorization", "xsftoken", "externalid", "awssecret",
        "awsaccesskey", "key",
    ))


def write_private_json(path: Path, value: Any) -> None:
    """Atomically write JSON through a mode-0600 temporary sibling."""
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent_info = parent.lstat()
    if stat.S_ISLNK(parent_info.st_mode) or not stat.S_ISDIR(parent_info.st_mode):
        raise PermissionError(f"private JSON parent must be a non-symlink directory: {parent}")
    serialized = json.dumps(value, indent=2) + "\n"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            os.fchmod(handle.fileno(), 0o600)
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
        final = path.lstat()
        if (
            not stat.S_ISREG(final.st_mode)
            or final.st_nlink != 1
            or stat.S_IMODE(final.st_mode) != 0o600
        ):
            raise PermissionError(f"private JSON failed final validation: {path}")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def append_step(
    state_dir: Path,
    section: str,
    step: str,
    idempotency_key: str,
    result: str,
    response: Any | None = None,
    notes: str | None = None,
) -> None:
    """Append a step record to ``apply-state.json`` (chmod 600)."""
    _secure_state_dir(state_dir, create=True)
    state_path = state_dir / "apply-state.json"
    try:
        state = _load_state(state_path)
    except FileNotFoundError:
        state = {"steps": []}
    except PermissionError as exc:
        if not state_path.exists() and not state_path.is_symlink():
            state = {"steps": []}
        else:
            raise exc
    state.setdefault("steps", []).append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "section": section,
        "step": step,
        "idempotency_key": idempotency_key,
        "result": result,
        "notes": notes,
        "response": redact(response),
    })
    serialized = json.dumps(state, indent=2) + "\n"
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=state_dir,
            prefix=".apply-state.",
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
            os.fchmod(handle.fileno(), 0o600)
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, state_path)
        os.chmod(state_path, 0o600)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def has_step(state_dir: Path, idempotency_key: str) -> bool:
    """Return True when a previous run recorded a successful step under the same idempotency key."""
    if not _secure_state_dir(state_dir, create=False):
        return False
    state_path = state_dir / "apply-state.json"
    try:
        state = _load_state(state_path)
    except PermissionError:
        if not state_path.exists() and not state_path.is_symlink():
            return False
        raise
    for entry in state.get("steps", []):
        if entry.get("idempotency_key") == idempotency_key and entry.get("result") == "success":
            return True
    return False


def read_secret_file(path: str | os.PathLike[str], allow_loose: bool = False) -> str:
    """Read one stable, bounded printable-ASCII token from a regular file."""
    p = Path(os.fspath(path))
    try:
        metadata = p.lstat()
    except OSError as exc:
        raise PermissionError(f"secret file is missing or unreadable: {p}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise PermissionError(f"secret file must be a regular, non-symlink file: {p}")
    if metadata.st_size == 0:
        raise PermissionError(f"secret file is missing or empty: {p}")
    if metadata.st_size > MAX_SECRET_BYTES:
        raise PermissionError(
            f"secret file exceeds the {MAX_SECRET_BYTES}-byte safety limit: {p}"
        )
    if metadata.st_nlink != 1:
        raise PermissionError(f"secret file must have exactly one hard link: {p}")
    mode = stat.S_IMODE(metadata.st_mode)
    if mode != 0o600 and not allow_loose:
        raise PermissionError(
            f"secret file {p} has loose permissions ({oct(mode)}); chmod 600 it or pass --allow-loose-token-perms."
        )

    if not hasattr(os, "O_NOFOLLOW"):
        raise PermissionError("platform lacks O_NOFOLLOW; cannot open secret files safely")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(p, flags)
        opened_before = os.fstat(descriptor)
        if not stat.S_ISREG(opened_before.st_mode) or opened_before.st_nlink != 1:
            raise PermissionError(f"secret file must remain a regular file while open: {p}")
        opened_mode = stat.S_IMODE(opened_before.st_mode)
        if opened_mode != 0o600 and not allow_loose:
            raise PermissionError(f"secret file permissions changed while opening: {p}")
        if _secret_stat_fingerprint(opened_before) != _secret_stat_fingerprint(metadata):
            raise PermissionError(f"secret file changed while it was being opened: {p}")

        first = _read_secret_bytes(descriptor, p)
        after_first = os.fstat(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        second = _read_secret_bytes(descriptor, p)
        opened_after = os.fstat(descriptor)
        path_after = p.lstat()
        expected = _secret_stat_fingerprint(opened_before)
        if any(
            _secret_stat_fingerprint(current) != expected
            for current in (after_first, opened_after, path_after)
        ):
            raise PermissionError(f"secret file changed while it was being read: {p}")
        if not hmac.compare_digest(
            hashlib.sha256(first).digest(), hashlib.sha256(second).digest()
        ):
            raise PermissionError(f"secret file content changed while it was being read: {p}")
    except PermissionError:
        raise
    except OSError as exc:
        raise PermissionError(f"secret file could not be opened safely: {p}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)

    try:
        raw = second.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ValueError(f"secret file must contain UTF-8 text: {p}") from exc
    return _parse_token_text(raw, p)


def _parse_token_text(raw: str, path: Path) -> str:
    """Accept one token with at most one LF or CRLF file terminator."""
    if raw.endswith("\r\n"):
        value = raw[:-2]
    elif raw.endswith("\n"):
        value = raw[:-1]
    else:
        value = raw
    if (
        not value
        or "\r" in value
        or "\n" in value
        or any(not (0x21 <= ord(character) <= 0x7E) for character in value)
    ):
        raise ValueError(
            f"secret file must contain exactly one non-empty printable-ASCII line "
            f"with at most one trailing LF or CRLF: {path}"
        )
    return value


def _secret_stat_fingerprint(metadata: os.stat_result) -> tuple[int, ...]:
    """Return metadata that must remain stable for the complete secret read."""
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _read_secret_bytes(descriptor: int, path: Path) -> bytes:
    """Read at most ``MAX_SECRET_BYTES`` plus one sentinel byte."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(descriptor, min(8192, MAX_SECRET_BYTES + 1 - total))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
        if total > MAX_SECRET_BYTES:
            raise PermissionError(
                f"secret file exceeds the {MAX_SECRET_BYTES}-byte safety limit: {path}"
            )
