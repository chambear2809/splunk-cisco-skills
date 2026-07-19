#!/usr/bin/env python3
"""Transactionally install or restore a Splunk OTel Collector config.

The command is intentionally narrow: it runs only as root on Linux, installs
one already-rendered configuration file, operates one systemd service, and
checks one loopback HTTP health endpoint. A current-generation pointer,
durable phase journal, runtime provenance, and exact file metadata make apply
and restore fail closed and recoverable. All machine-readable output is a
small, fixed-schema JSON object; subprocess output and HTTP bodies are never
reflected.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import errno
import fcntl
import hashlib
import hmac
import ipaddress
import json
import math
import os
import re
import secrets
import signal
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, BinaryIO, Mapping, Sequence


SCHEMA_VERSION = "lemonade-collector-transaction/v2"
JOURNAL_SCHEMA_VERSION = "lemonade-collector-journal/v2"
CURRENT_SCHEMA_VERSION = "lemonade-collector-current/v2"
DEFAULT_HEALTH_TIMEOUT_SECONDS = 15.0
MAX_HEALTH_TIMEOUT_SECONDS = 30.0
MAX_CONFIG_BYTES = 32 * 1024 * 1024
MAX_BINARY_BYTES = 1024 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_UNIT_BYTES = 8 * 1024 * 1024
MAX_XATTR_BYTES = 1024 * 1024
MAX_XATTR_COUNT = 128
SYSTEMCTL_CANDIDATES = ("/usr/bin/systemctl", "/bin/systemctl")
DPKG_QUERY = "/usr/bin/dpkg-query"
PACKAGE_ALLOWLIST = ("lemonade-server", "splunk-otel-collector")
MACHINE_ID_CANDIDATES = (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id"))
CURRENT_FILE_NAME = "current.json"
SERVICE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@:-]{0,254}$")
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
GENERATION_RE = re.compile(r"^[0-9a-f]{32}$")
SAFE_METADATA_RE = re.compile(r"^[A-Za-z0-9_.@:/+~-]{1,256}$")
SAFE_VERSION_RE = re.compile(r"^[A-Za-z0-9.+:~_-]{1,256}$")
SERVICE_METADATA_FIELDS = {
    "Id": "id",
    "LoadState": "load_state",
    "ActiveState": "active_state",
    "SubState": "sub_state",
    "UnitFileState": "unit_file_state",
}
SUBPROCESS_ENV = {
    "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG": "C",
    "LC_ALL": "C",
}
APPLY_PHASES = (
    "prepared",
    "apply_install_pending",
    "apply_config_installed",
    "apply_restart_pending",
    "apply_service_restarted",
    "apply_health_pending",
    "applied",
)
RESTORE_PHASES = (
    "restore_started",
    "restore_config_pending",
    "restore_config_restored",
    "restore_daemon_reload_pending",
    "restore_daemon_reload_done",
    "restore_enablement_pending",
    "restore_enablement_done",
    "restore_active_pending",
    "restore_active_done",
    "restore_health_pending",
    "restored",
)
RECOVERY_PHASES = frozenset({"recovery_required"})
ALL_PHASES = frozenset((*APPLY_PHASES, *RESTORE_PHASES, *RECOVERY_PHASES))
TERMINAL_PHASES = frozenset({"applied", "restored"})
RESTORE_PHASE_INDEX = {phase: index for index, phase in enumerate(RESTORE_PHASES)}
SUPPORTED_ACTIVE_STATES = frozenset({"active", "inactive"})
SUPPORTED_UNIT_FILE_STATES = frozenset({"enabled", "disabled"})
RUNTIME_RECOVERY_CODES = frozenset(
    {
        "collector_binary_drift",
        "host_drift",
        "package_inventory_failed",
        "package_version_drift",
        "service_fingerprint_drift",
        "service_fingerprint_failed",
        "service_metadata_failed",
        "service_state_disagreement",
        "service_state_drift",
        "service_state_failed",
        "systemctl_missing",
        "unsupported_active_state",
        "unsupported_unit_file_state",
    }
)


class TransactionError(RuntimeError):
    """An operational error with a fixed, safe-to-display description."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message


class JsonArgumentParser(argparse.ArgumentParser):
    """Make malformed CLI input follow the JSON-only error contract."""

    def error(self, message: str) -> None:  # noqa: ARG002
        raise TransactionError("invalid_arguments", "command arguments are invalid")


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise TransactionError(
            "health_redirect", "health endpoint redirects are not allowed"
        )


def emit(document: Mapping[str, Any], *, stream: Any = sys.stdout) -> None:
    stream.write(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")
    stream.flush()


def validate_runtime() -> None:
    if not sys.platform.startswith("linux"):
        raise TransactionError(
            "unsupported_platform", "apply and restore require Linux"
        )
    if os.geteuid() != 0:
        raise TransactionError("root_required", "apply and restore require root")


def validate_service_name(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not SERVICE_RE.fullmatch(value)
        or value.startswith("-")
    ):
        raise TransactionError("invalid_service", "service name is invalid")
    return value


def validate_sha256(value: Any) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise TransactionError("invalid_sha256", "expected SHA-256 is invalid")
    return value.lower()


def validate_timeout(value: Any) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value <= 0
        or value > MAX_HEALTH_TIMEOUT_SECONDS
    ):
        raise TransactionError(
            "invalid_timeout",
            f"health timeout must be greater than zero and at most {MAX_HEALTH_TIMEOUT_SECONDS:g} seconds",
        )
    return float(value)


def absolute_path(value: Any, label: str) -> Path:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 4096
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
    ):
        raise TransactionError("invalid_path", f"{label} path is invalid")
    path = Path(value)
    if not path.is_absolute():
        raise TransactionError("invalid_path", f"{label} path must be absolute")
    normalized = Path(os.path.normpath(value))
    if str(normalized) != value or normalized == Path("/"):
        raise TransactionError("invalid_path", f"{label} path is not canonical")
    return normalized


def validate_loopback_health_url(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 2048
        or "%" in value
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
    ):
        raise TransactionError("invalid_health_url", "health URL is invalid")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise TransactionError("invalid_health_url", "health URL is invalid") from exc
    if (
        parsed.scheme != "http"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not parsed.hostname
        or port is None
        or not 1 <= port <= 65535
    ):
        raise TransactionError(
            "invalid_health_url",
            "health URL must be an explicit-port loopback HTTP URL",
        )
    try:
        host = ipaddress.ip_address(parsed.hostname)
    except ValueError as exc:
        raise TransactionError(
            "invalid_health_url", "health URL host must be a loopback IP literal"
        ) from exc
    if not host.is_loopback:
        raise TransactionError(
            "invalid_health_url", "health URL host must be a loopback IP literal"
        )
    return value


def _path_parts(path: Path) -> list[Path]:
    parts: list[Path] = []
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        parts.append(current)
    return parts


def assert_no_symlink_components(
    path: Path, *, label: str, allow_missing_final: bool = False
) -> None:
    components = _path_parts(path)
    for index, component in enumerate(components):
        try:
            metadata = os.lstat(component)
        except FileNotFoundError as exc:
            if allow_missing_final and index == len(components) - 1:
                return
            raise TransactionError(
                "unsafe_path", f"{label} path does not exist"
            ) from exc
        except OSError as exc:
            raise TransactionError(
                "unsafe_path", f"{label} path cannot be inspected"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise TransactionError(
                "unsafe_path", f"{label} path contains a symbolic link"
            )
        if index < len(components) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise TransactionError("unsafe_path", f"{label} parent is not a directory")


def assert_root_owned_secure_path(
    path: Path,
    *,
    label: str,
    include_final: bool,
    allow_missing_final: bool = False,
) -> None:
    """Require a root-owned path chain with no group/other-writable component."""

    components = [Path(path.anchor), *_path_parts(path)]
    last_index = len(components) - 1
    for index, component in enumerate(components):
        if index == last_index and not include_final:
            break
        try:
            metadata = os.lstat(component)
        except FileNotFoundError as exc:
            if allow_missing_final and index == last_index:
                return
            raise TransactionError(
                "unsafe_path", f"{label} path does not exist"
            ) from exc
        except OSError as exc:
            raise TransactionError(
                "unsafe_path", f"{label} path cannot be inspected"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise TransactionError(
                "unsafe_path", f"{label} path contains a symbolic link"
            )
        if index < last_index and not stat.S_ISDIR(metadata.st_mode):
            raise TransactionError("unsafe_path", f"{label} parent is not a directory")
        if metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) & 0o022:
            raise TransactionError(
                "unsafe_path",
                f"{label} path must be root-owned and not group/other-writable",
            )


def assert_secure_directory(
    path: Path, *, label: str, fix_mode: bool
) -> os.stat_result:
    assert_no_symlink_components(path, label=label)
    metadata = os.lstat(path)
    if not stat.S_ISDIR(metadata.st_mode):
        raise TransactionError("unsafe_directory", f"{label} is not a directory")
    if metadata.st_uid != os.geteuid():
        raise TransactionError(
            "unsafe_directory", f"{label} is not owned by the current user"
        )
    if fix_mode:
        try:
            os.chmod(path, 0o700, follow_symlinks=False)
        except OSError as exc:
            raise TransactionError(
                "unsafe_directory", f"{label} mode cannot be secured"
            ) from exc
        metadata = os.lstat(path)
    if stat.S_IMODE(metadata.st_mode) != 0o700:
        raise TransactionError("unsafe_directory", f"{label} must have mode 0700")
    return metadata


def ensure_state_root(path: Path) -> None:
    assert_root_owned_secure_path(
        path.parent, label="state root parent", include_final=True
    )
    created = False
    try:
        os.mkdir(path, 0o700)
        created = True
    except FileExistsError:
        pass
    except OSError as exc:
        raise TransactionError(
            "state_root_failed", "state root cannot be created"
        ) from exc
    # Never chmod an arbitrary pre-existing directory supplied to a root tool.
    # A pre-existing state root must already satisfy the private-directory
    # contract; only a directory created by this invocation is normalized.
    assert_secure_directory(path, label="state root", fix_mode=created)
    assert_root_owned_secure_path(path, label="state root", include_final=True)
    if created:
        _fsync_directory(path.parent)


def _safe_open_regular(path: Path, *, label: str) -> tuple[int, os.stat_result]:
    assert_no_symlink_components(path, label=label)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise TransactionError(
            "unsafe_file", f"{label} cannot be opened safely"
        ) from exc
    try:
        opened = os.fstat(fd)
        named = os.lstat(path)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or stat.S_ISLNK(named.st_mode)
            or opened.st_dev != named.st_dev
            or opened.st_ino != named.st_ino
        ):
            raise TransactionError(
                "unsafe_file", f"{label} must be a non-linked single-link regular file"
            )
        return fd, opened
    except Exception:
        os.close(fd)
        raise


def read_regular_file(
    path: Path, *, label: str, max_bytes: int
) -> tuple[bytes, os.stat_result]:
    fd, metadata = _safe_open_regular(path, label=label)
    try:
        if metadata.st_size < 0 or metadata.st_size > max_bytes:
            raise TransactionError("file_too_large", f"{label} exceeds the size limit")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining > 0:
            chunk = os.read(fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > max_bytes:
            raise TransactionError("file_too_large", f"{label} exceeds the size limit")
        after = os.fstat(fd)
        if (
            after.st_dev != metadata.st_dev
            or after.st_ino != metadata.st_ino
            or after.st_size != metadata.st_size
            or after.st_mtime_ns != metadata.st_mtime_ns
        ):
            raise TransactionError("file_changed", f"{label} changed while it was read")
        return payload, metadata
    finally:
        os.close(fd)


def hash_regular_file(
    path: Path, *, label: str, max_bytes: int
) -> tuple[str, os.stat_result]:
    fd, metadata = _safe_open_regular(path, label=label)
    try:
        if metadata.st_size < 0 or metadata.st_size > max_bytes:
            raise TransactionError("file_too_large", f"{label} exceeds the size limit")
        digest = hashlib.sha256()
        remaining = max_bytes + 1
        total = 0
        while remaining > 0:
            chunk = os.read(fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
            remaining -= len(chunk)
        if total > max_bytes:
            raise TransactionError("file_too_large", f"{label} exceeds the size limit")
        after = os.fstat(fd)
        if (
            after.st_dev != metadata.st_dev
            or after.st_ino != metadata.st_ino
            or after.st_size != metadata.st_size
            or after.st_mtime_ns != metadata.st_mtime_ns
        ):
            raise TransactionError("file_changed", f"{label} changed while it was read")
        return digest.hexdigest(), metadata
    finally:
        os.close(fd)


def _xattr_functions() -> tuple[Any, Any, Any, Any] | None:
    functions = tuple(
        getattr(os, name, None)
        for name in ("listxattr", "getxattr", "setxattr", "removexattr")
    )
    if all(callable(function) for function in functions):
        return functions  # type: ignore[return-value]
    if sys.platform.startswith("linux"):
        raise TransactionError(
            "metadata_unsupported",
            "Python extended-attribute support is required on Linux",
        )
    return None


def read_xattrs(
    path: Path, metadata: os.stat_result, *, label: str
) -> dict[str, bytes]:
    functions = _xattr_functions()
    if functions is None:
        return {}
    listxattr, getxattr, _, _ = functions
    try:
        names = listxattr(path, follow_symlinks=False)
    except OSError as exc:
        if exc.errno in {errno.ENOTSUP, getattr(errno, "EOPNOTSUPP", errno.ENOTSUP)}:
            return {}
        raise TransactionError(
            "metadata_read_failed", f"{label} extended attributes cannot be read"
        ) from exc
    if not isinstance(names, list) or len(names) > MAX_XATTR_COUNT:
        raise TransactionError(
            "metadata_too_large", f"{label} has too many extended attributes"
        )
    captured: dict[str, bytes] = {}
    total = 0
    for name in sorted(names):
        if (
            not isinstance(name, str)
            or not name
            or len(name.encode("utf-8")) > 255
            or any(
                ord(character) < 0x20 or ord(character) == 0x7F for character in name
            )
        ):
            raise TransactionError(
                "metadata_invalid", f"{label} has an invalid extended attribute"
            )
        try:
            value = getxattr(path, name, follow_symlinks=False)
        except OSError as exc:
            raise TransactionError(
                "metadata_read_failed", f"{label} extended attributes changed"
            ) from exc
        if not isinstance(value, bytes):
            raise TransactionError(
                "metadata_invalid", f"{label} has an invalid extended attribute"
            )
        total += len(name.encode("utf-8")) + len(value)
        if total > MAX_XATTR_BYTES:
            raise TransactionError(
                "metadata_too_large", f"{label} extended attributes exceed the limit"
            )
        captured[name] = value
    after = os.lstat(path)
    if (
        after.st_dev != metadata.st_dev
        or after.st_ino != metadata.st_ino
        or after.st_size != metadata.st_size
        or after.st_mtime_ns != metadata.st_mtime_ns
    ):
        raise TransactionError("file_changed", f"{label} changed while it was read")
    return captured


def encode_xattrs(xattrs: Mapping[str, bytes]) -> bytes:
    document = [
        {"name": name, "value": base64.b64encode(value).decode("ascii")}
        for name, value in sorted(xattrs.items())
    ]
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def decode_xattrs(payload: bytes) -> dict[str, bytes]:
    try:
        document = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TransactionError(
            "invalid_manifest", "extended-attribute snapshot is invalid"
        ) from exc
    if not isinstance(document, list) or len(document) > MAX_XATTR_COUNT:
        raise TransactionError(
            "invalid_manifest", "extended-attribute snapshot is invalid"
        )
    result: dict[str, bytes] = {}
    total = 0
    for item in document:
        if not isinstance(item, dict) or set(item) != {"name", "value"}:
            raise TransactionError(
                "invalid_manifest", "extended-attribute snapshot is invalid"
            )
        name = item["name"]
        encoded = item["value"]
        if (
            not isinstance(name, str)
            or not name
            or len(name.encode("utf-8")) > 255
            or any(
                ord(character) < 0x20 or ord(character) == 0x7F for character in name
            )
            or not isinstance(encoded, str)
            or name in result
        ):
            raise TransactionError(
                "invalid_manifest", "extended-attribute snapshot is invalid"
            )
        try:
            value = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise TransactionError(
                "invalid_manifest", "extended-attribute snapshot is invalid"
            ) from exc
        total += len(name.encode("utf-8")) + len(value)
        if total > MAX_XATTR_BYTES:
            raise TransactionError(
                "invalid_manifest", "extended-attribute snapshot is too large"
            )
        result[name] = value
    return result


def apply_xattrs(path: Path, expected: Mapping[str, bytes]) -> None:
    functions = _xattr_functions()
    if functions is None:
        if expected:
            raise TransactionError(
                "metadata_unsupported", "extended attributes cannot be restored"
            )
        return
    listxattr, _, setxattr, removexattr = functions
    try:
        existing = set(listxattr(path, follow_symlinks=False))
        for name in existing - set(expected):
            removexattr(path, name, follow_symlinks=False)
        for name, value in expected.items():
            setxattr(path, name, value, follow_symlinks=False)
    except OSError as exc:
        raise TransactionError(
            "metadata_restore_failed", "live config metadata cannot be restored"
        ) from exc


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_all(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    offset = 0
    while offset < len(view):
        written = os.write(fd, view[offset:])
        if written <= 0:
            raise OSError("short write")
        offset += written


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise TransactionError(
            "fsync_failed", "transaction directory cannot be synchronized"
        ) from exc
    try:
        os.fsync(fd)
    except OSError as exc:
        raise TransactionError(
            "fsync_failed", "transaction directory cannot be synchronized"
        ) from exc
    finally:
        os.close(fd)


def write_exclusive(path: Path, payload: bytes, *, mode: int, label: str) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        fd = os.open(path, flags, mode)
    except OSError as exc:
        raise TransactionError(
            "state_write_failed", f"{label} cannot be created"
        ) from exc
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise TransactionError("unsafe_file", f"{label} is not a safe regular file")
        os.fchmod(fd, mode)
        _write_all(fd, payload)
        os.fsync(fd)
    except OSError as exc:
        raise TransactionError(
            "state_write_failed", f"{label} cannot be synchronized"
        ) from exc
    finally:
        os.close(fd)
    _fsync_directory(path.parent)


def write_atomic_private(path: Path, payload: bytes, *, label: str) -> None:
    assert_secure_directory(path.parent, label=f"{label} parent", fix_mode=False)
    try:
        existing = os.lstat(path)
    except FileNotFoundError:
        existing = None
    except OSError as exc:
        raise TransactionError(
            "state_write_failed", f"{label} cannot be inspected"
        ) from exc
    if existing is not None and (
        not stat.S_ISREG(existing.st_mode)
        or existing.st_nlink != 1
        or existing.st_uid != os.geteuid()
        or stat.S_IMODE(existing.st_mode) != 0o600
    ):
        raise TransactionError("unsafe_file", f"{label} is not a safe private file")
    try:
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    except OSError as exc:
        raise TransactionError(
            "state_write_failed", f"{label} cannot be created"
        ) from exc
    temporary = Path(temporary_name)
    installed = False
    try:
        opened = os.fstat(fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_uid != os.geteuid()
        ):
            raise TransactionError("unsafe_file", f"{label} temporary file is unsafe")
        os.fchmod(fd, 0o600)
        _write_all(fd, payload)
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(temporary, path)
        installed = True
        _fsync_directory(path.parent)
    except TransactionError:
        raise
    except OSError as exc:
        raise TransactionError(
            "state_write_failed", f"{label} cannot be synchronized"
        ) from exc
    finally:
        if fd >= 0:
            os.close(fd)
        if not installed:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def atomic_install(
    path: Path,
    payload: bytes,
    *,
    uid: int,
    gid: int,
    mode: int,
    xattrs: Mapping[str, bytes] | None = None,
) -> None:
    assert_root_owned_secure_path(
        path.parent, label="live config parent", include_final=True
    )
    if not stat.S_ISDIR(os.lstat(path.parent).st_mode):
        raise TransactionError("unsafe_path", "live config parent is not a directory")
    try:
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    except OSError as exc:
        raise TransactionError(
            "install_failed", "temporary live config cannot be created"
        ) from exc
    temporary = Path(temporary_name)
    installed = False
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise TransactionError(
                "unsafe_file", "temporary live config is not a safe regular file"
            )
        os.fchown(fd, uid, gid)
        # chown may clear set-ID bits, so apply the exact snapshotted mode last.
        os.fchmod(fd, mode)
        _write_all(fd, payload)
        apply_xattrs(temporary, xattrs or {})
        applied = os.fstat(fd)
        if (
            applied.st_uid != uid
            or applied.st_gid != gid
            or stat.S_IMODE(applied.st_mode) != mode
        ):
            raise TransactionError(
                "metadata_restore_failed", "live config metadata cannot be restored"
            )
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(temporary, path)
        installed = True
        _fsync_directory(path.parent)
    except TransactionError:
        raise
    except OSError as exc:
        raise TransactionError(
            "install_failed", "live config cannot be installed atomically"
        ) from exc
    finally:
        if fd >= 0:
            os.close(fd)
        if not installed:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def verify_installed_file(
    path: Path,
    expected_payload: bytes,
    *,
    uid: int,
    gid: int,
    mode: int,
    label: str,
    xattrs: Mapping[str, bytes] | None = None,
) -> None:
    payload, metadata = read_regular_file(path, label=label, max_bytes=MAX_CONFIG_BYTES)
    actual_xattrs = read_xattrs(path, metadata, label=label)
    if (
        not hmac.compare_digest(sha256_bytes(payload), sha256_bytes(expected_payload))
        or metadata.st_uid != uid
        or metadata.st_gid != gid
        or stat.S_IMODE(metadata.st_mode) != mode
        or actual_xattrs != dict(xattrs or {})
    ):
        raise TransactionError(
            "install_verification_failed", f"{label} verification failed"
        )


def systemctl_path() -> str:
    for candidate in SYSTEMCTL_CANDIDATES:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    raise TransactionError("systemctl_missing", "systemctl is not available")


def run_command(
    arguments: Sequence[str], *, timeout: float = 30.0
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(arguments),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=SUBPROCESS_ENV,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TransactionError(
            "command_failed", "required local command could not be executed"
        ) from exc


def service_boolean(systemctl: str, operation: str, service: str) -> bool:
    result = run_command((systemctl, operation, "--quiet", "--", service))
    if result.returncode == 0:
        return True
    # systemctl uses nonzero for the ordinary false state.  Values at or above
    # four generally indicate an unknown unit or operational failure.
    if result.returncode in {1, 2, 3}:
        return False
    raise TransactionError("service_state_failed", "service state cannot be determined")


def service_metadata(systemctl: str, service: str) -> dict[str, str]:
    properties = ",".join(SERVICE_METADATA_FIELDS)
    result = run_command((systemctl, "show", f"--property={properties}", "--", service))
    if result.returncode != 0:
        return {}
    selected: dict[str, str] = {}
    for line in result.stdout[:8192].splitlines():
        key, separator, value = line.partition("=")
        output_key = SERVICE_METADATA_FIELDS.get(key)
        if separator and output_key and SAFE_METADATA_RE.fullmatch(value):
            selected[output_key] = value
    return selected


def require_loaded_service(metadata: Any, service: str) -> None:
    """Require an exact, positively loaded systemd unit identity."""

    if (
        not isinstance(metadata, dict)
        or metadata.get("id") != service
        or metadata.get("load_state") != "loaded"
    ):
        raise TransactionError(
            "service_metadata_failed",
            "requested systemd service identity and loaded state cannot be verified",
        )


def require_supported_service_metadata(metadata: Any, service: str) -> tuple[str, str]:
    require_loaded_service(metadata, service)
    active_state = metadata.get("active_state")
    unit_file_state = metadata.get("unit_file_state")
    if active_state not in SUPPORTED_ACTIVE_STATES:
        raise TransactionError(
            "unsupported_active_state",
            "systemd service ActiveState must be exactly active or inactive",
        )
    if unit_file_state not in SUPPORTED_UNIT_FILE_STATES:
        raise TransactionError(
            "unsupported_unit_file_state",
            "systemd service UnitFileState must be exactly enabled or disabled",
        )
    return active_state, unit_file_state


def service_state_snapshot(
    systemctl: str,
    service: str,
    *,
    expected_active_state: str | None = None,
    expected_unit_file_state: str | None = None,
) -> dict[str, str]:
    metadata = service_metadata(systemctl, service)
    active_state, unit_file_state = require_supported_service_metadata(
        metadata, service
    )
    observed_active = service_boolean(systemctl, "is-active", service)
    if observed_active != (active_state == "active"):
        raise TransactionError(
            "service_state_disagreement",
            "systemd ActiveState disagrees with systemctl is-active",
        )
    if expected_active_state is not None and active_state != expected_active_state:
        raise TransactionError(
            "service_state_drift", "systemd service ActiveState changed"
        )
    if (
        expected_unit_file_state is not None
        and unit_file_state != expected_unit_file_state
    ):
        raise TransactionError(
            "service_state_drift", "systemd service UnitFileState changed"
        )
    return metadata


def service_unit_fingerprint(systemctl: str, service: str) -> str:
    result = run_command(
        (
            systemctl,
            "show",
            "--property=FragmentPath,DropInPaths",
            "--",
            service,
        )
    )
    if result.returncode != 0:
        raise TransactionError(
            "service_fingerprint_failed", "systemd unit fingerprint cannot be read"
        )
    selected: dict[str, str] = {}
    for line in result.stdout[:16384].splitlines():
        key, separator, value = line.partition("=")
        if (
            key not in {"FragmentPath", "DropInPaths"}
            or not separator
            or key in selected
        ):
            raise TransactionError(
                "service_fingerprint_failed",
                "systemd unit fingerprint cannot be read",
            )
        if len(value) > 8192 or any(
            ord(character) < 0x20 or ord(character) == 0x7F for character in value
        ):
            raise TransactionError(
                "service_fingerprint_failed",
                "systemd unit fingerprint cannot be read",
            )
        selected[key] = value
    if set(selected) != {"FragmentPath", "DropInPaths"} or not selected["FragmentPath"]:
        raise TransactionError(
            "service_fingerprint_failed", "systemd unit fingerprint cannot be read"
        )
    raw_paths = [selected["FragmentPath"]]
    if selected["DropInPaths"]:
        raw_paths.extend(selected["DropInPaths"].split(" "))
    if len(raw_paths) > 128 or len(set(raw_paths)) != len(raw_paths):
        raise TransactionError(
            "service_fingerprint_failed", "systemd unit fingerprint cannot be read"
        )
    digest = hashlib.sha256(b"lemonade-systemd-unit-v1\0")
    for raw_path in sorted(raw_paths):
        try:
            path = absolute_path(raw_path, "systemd unit")
            assert_root_owned_secure_path(
                path, label="systemd unit", include_final=True
            )
            file_hash, _ = hash_regular_file(
                path, label="systemd unit", max_bytes=MAX_UNIT_BYTES
            )
        except TransactionError as exc:
            raise TransactionError(
                "service_fingerprint_failed",
                "systemd unit fingerprint cannot be read",
            ) from exc
        digest.update(str(path).encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def revalidate_unit(
    systemctl: str,
    service: str,
    expected_fingerprint: str,
    *,
    expected_active_state: str | None = None,
    expected_unit_file_state: str | None = None,
) -> dict[str, str]:
    metadata = service_state_snapshot(
        systemctl,
        service,
        expected_active_state=expected_active_state,
        expected_unit_file_state=expected_unit_file_state,
    )
    actual = service_unit_fingerprint(systemctl, service)
    if not hmac.compare_digest(actual, validate_sha256(expected_fingerprint)):
        raise TransactionError(
            "service_fingerprint_drift",
            "systemd unit or drop-in fingerprint changed",
        )
    return metadata


def package_versions() -> dict[str, str]:
    if not (os.path.isfile(DPKG_QUERY) and os.access(DPKG_QUERY, os.X_OK)):
        return {}
    result = run_command(
        (
            DPKG_QUERY,
            "-W",
            "-f=${binary:Package}\t${Version}\n",
            "--",
            *PACKAGE_ALLOWLIST,
        )
    )
    if result.returncode != 0:
        return {}
    versions: dict[str, str] = {}
    for line in result.stdout[:8192].splitlines():
        package, separator, version = line.partition("\t")
        if (
            separator
            and package in PACKAGE_ALLOWLIST
            and SAFE_VERSION_RE.fullmatch(version)
        ):
            versions[package] = version
    return versions


def validated_package_versions(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != set(PACKAGE_ALLOWLIST):
        raise TransactionError(
            "package_inventory_failed", "required package versions cannot be verified"
        )
    result: dict[str, str] = {}
    for package in PACKAGE_ALLOWLIST:
        version = value.get(package)
        if not isinstance(version, str) or not SAFE_VERSION_RE.fullmatch(version):
            raise TransactionError(
                "package_inventory_failed",
                "required package versions cannot be verified",
            )
        result[package] = version
    return result


def host_fingerprint() -> str:
    for candidate in MACHINE_ID_CANDIDATES:
        try:
            payload, metadata = read_regular_file(
                candidate, label="machine identity", max_bytes=4096
            )
        except TransactionError:
            continue
        if (
            metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) & 0o022
            or not payload.strip()
            or len(payload.strip()) > 256
        ):
            continue
        return sha256_bytes(b"lemonade-host-v1\0" + payload.strip())
    raise TransactionError(
        "host_identity_failed", "sanitized host identity cannot be verified"
    )


def collector_binary_provenance(
    path: Path,
    expected_sha256: str,
    *,
    expected_device: int | None = None,
    expected_inode: int | None = None,
) -> dict[str, Any]:
    try:
        assert_root_owned_secure_path(
            path, label="collector binary", include_final=True
        )
        actual_sha256, metadata = hash_regular_file(
            path, label="collector binary", max_bytes=MAX_BINARY_BYTES
        )
    except TransactionError as exc:
        raise TransactionError(
            "collector_binary_drift",
            "collector binary path or SHA-256 cannot be verified",
        ) from exc
    if (
        metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) & 0o022
        or not stat.S_IMODE(metadata.st_mode) & 0o111
        or not hmac.compare_digest(actual_sha256, validate_sha256(expected_sha256))
        or (expected_device is not None and metadata.st_dev != expected_device)
        or (expected_inode is not None and metadata.st_ino != expected_inode)
    ):
        raise TransactionError(
            "collector_binary_drift",
            "collector binary path or SHA-256 cannot be verified",
        )
    return {
        "path": str(path),
        "sha256": actual_sha256,
        "device": metadata.st_dev,
        "inode": metadata.st_ino,
    }


def service_action(systemctl: str, action: str, service: str) -> None:
    if action not in {"daemon-reload", "restart", "stop", "enable", "disable"}:
        raise TransactionError("internal_error", "unsupported service action")
    arguments = (
        (systemctl, action)
        if action == "daemon-reload"
        else (
            systemctl,
            action,
            "--",
            service,
        )
    )
    result = run_command(arguments)
    if result.returncode != 0:
        raise TransactionError("service_action_failed", f"service {action} failed")


def build_health_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        NoRedirectHandler(),
    )


def wait_for_health(url: str, timeout: float) -> dict[str, Any]:
    opener = build_health_opener()
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "*/*",
            "Accept-Encoding": "identity",
            "User-Agent": "lemonade-collector-transaction/1",
        },
    )
    deadline = time.monotonic() + timeout
    last_status: int | None = None
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            response = opener.open(request, timeout=min(2.0, remaining))
        except urllib.error.HTTPError as exc:
            last_status = int(exc.code)
            exc.close()
        except TransactionError:
            raise
        except Exception:
            pass
        else:
            try:
                last_status = int(response.getcode())
            finally:
                # Intentionally do not consume or reflect the response body.
                response.close()
            if 200 <= last_status < 300:
                return {"checked": True, "ok": True, "status_code": last_status}
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(0.25, remaining))
    result: dict[str, Any] = {"checked": True, "ok": False}
    if last_status is not None:
        result["status_code"] = last_status
    raise TransactionError("health_failed", "health verification failed")


def acquire_lock(state_root: Path) -> BinaryIO:
    lock_path = state_root / ".transaction.lock"
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        fd = os.open(lock_path, flags, 0o600)
        metadata = os.fstat(fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != os.geteuid()
        ):
            raise TransactionError(
                "unsafe_lock", "transaction lock is not a safe regular file"
            )
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return os.fdopen(fd, "r+b", closefd=True)
    except BlockingIOError as exc:
        try:
            os.close(fd)
        except UnboundLocalError:
            pass
        raise TransactionError(
            "transaction_busy", "another collector transaction is active"
        ) from exc
    except Exception:
        try:
            os.close(fd)
        except (OSError, UnboundLocalError):
            pass
        raise


def create_state_dir(state_root: Path, generation: str) -> Path:
    if not GENERATION_RE.fullmatch(generation):
        raise TransactionError("internal_error", "transaction generation is invalid")
    state_dir = state_root / f"transaction-{generation}"
    try:
        os.mkdir(state_dir, 0o700)
    except OSError as exc:
        raise TransactionError(
            "state_dir_failed", "transaction state directory cannot be created"
        ) from exc
    assert_secure_directory(
        state_dir, label="transaction state directory", fix_mode=False
    )
    _fsync_directory(state_root)
    return state_dir


def utc_now() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def manifest_bytes(document: Mapping[str, Any]) -> bytes:
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def snapshot_manifest(
    *,
    generation: str,
    state_root: Path,
    state_dir: Path,
    backup_path: Path,
    xattrs_path: Path,
    xattrs_sha256: str,
    journal_path: Path,
    staged_path: Path,
    live_path: Path,
    staged_sha256: str,
    live_sha256: str,
    live_metadata: os.stat_result,
    service: str,
    health_url: str,
    health_timeout: float,
    active_state: str,
    unit_file_state: str,
    metadata: Mapping[str, str],
    packages: Mapping[str, str],
    host_id: str,
    collector_binary: Mapping[str, Any],
    unit_fingerprint: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generation": generation,
        "created_at": utc_now(),
        "state_root": str(state_root),
        "state_dir": str(state_dir),
        "backup_path": str(backup_path),
        "xattrs_path": str(xattrs_path),
        "xattrs_sha256": xattrs_sha256,
        "journal_path": str(journal_path),
        "staged_path": str(staged_path),
        "live_path": str(live_path),
        "staged_sha256": staged_sha256,
        "backup_sha256": live_sha256,
        "live_metadata": {
            "uid": live_metadata.st_uid,
            "gid": live_metadata.st_gid,
            "mode": stat.S_IMODE(live_metadata.st_mode),
        },
        "service": {
            "name": service,
            "active_state": active_state,
            "unit_file_state": unit_file_state,
            "was_active": active_state == "active",
            "was_enabled": unit_file_state == "enabled",
            "metadata": dict(metadata),
        },
        "package_versions": dict(packages),
        "host_fingerprint": host_id,
        "collector_binary": dict(collector_binary),
        "service_unit_fingerprint": unit_fingerprint,
        "health": {"url": health_url, "timeout_seconds": health_timeout},
    }


def _manifest_path(document: Mapping[str, Any], key: str) -> Path:
    value = document.get(key)
    if not isinstance(value, str):
        raise TransactionError("invalid_manifest", "transaction manifest is invalid")
    return absolute_path(value, f"manifest {key}")


def _validate_private_file(metadata: os.stat_result, label: str) -> None:
    if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise TransactionError("unsafe_file", f"{label} must be owner-only mode 0600")


def validate_private_artifact_metadata(metadata: os.stat_result, *, label: str) -> None:
    if (
        metadata.st_uid != 0
        or metadata.st_gid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
    ):
        raise TransactionError(
            "unsafe_file",
            f"{label} must be a root-owned, root-group, single-link regular file "
            "with mode 0600",
        )


def validate_manifest(document: Any, manifest_path: Path) -> dict[str, Any]:
    if (
        not isinstance(document, dict)
        or document.get("schema_version") != SCHEMA_VERSION
    ):
        raise TransactionError("invalid_manifest", "transaction manifest is invalid")
    generation = document.get("generation")
    if not isinstance(generation, str) or not GENERATION_RE.fullmatch(generation):
        raise TransactionError("invalid_manifest", "transaction manifest is invalid")
    state_root = _manifest_path(document, "state_root")
    state_dir = _manifest_path(document, "state_dir")
    backup_path = _manifest_path(document, "backup_path")
    xattrs_path = _manifest_path(document, "xattrs_path")
    journal_path = _manifest_path(document, "journal_path")
    live_path = _manifest_path(document, "live_path")
    _manifest_path(document, "staged_path")
    if (
        state_dir != state_root / f"transaction-{generation}"
        or manifest_path != state_dir / "manifest.json"
        or backup_path != state_dir / "live-config.backup"
        or xattrs_path != state_dir / "live-config.xattrs.json"
        or journal_path != state_dir / "journal.json"
    ):
        raise TransactionError(
            "invalid_manifest", "transaction manifest path is invalid"
        )
    assert_root_owned_secure_path(state_root, label="state root", include_final=True)
    assert_secure_directory(state_root, label="state root", fix_mode=False)
    assert_secure_directory(
        state_dir, label="transaction state directory", fix_mode=False
    )
    assert_root_owned_secure_path(live_path, label="live config", include_final=True)

    service = document.get("service")
    health = document.get("health")
    metadata = document.get("live_metadata")
    collector = document.get("collector_binary")
    if (
        not isinstance(service, dict)
        or not isinstance(service.get("was_active"), bool)
        or not isinstance(service.get("was_enabled"), bool)
        or not isinstance(service.get("metadata"), dict)
        or not isinstance(health, dict)
        or not isinstance(metadata, dict)
        or not isinstance(collector, dict)
    ):
        raise TransactionError("invalid_manifest", "transaction manifest is invalid")
    service_name = validate_service_name(service.get("name", ""))
    active_state, unit_file_state = require_supported_service_metadata(
        service["metadata"], service_name
    )
    if (
        service.get("active_state") != active_state
        or service.get("unit_file_state") != unit_file_state
        or service["was_active"] != (active_state == "active")
        or service["was_enabled"] != (unit_file_state == "enabled")
    ):
        raise TransactionError("invalid_manifest", "transaction manifest is invalid")
    if any(
        key not in SERVICE_METADATA_FIELDS.values()
        or not isinstance(value, str)
        or not SAFE_METADATA_RE.fullmatch(value)
        for key, value in service["metadata"].items()
    ):
        raise TransactionError("invalid_manifest", "transaction manifest is invalid")
    validate_loopback_health_url(health.get("url", ""))
    validate_timeout(health.get("timeout_seconds", 0))
    validate_sha256(document.get("staged_sha256", ""))
    validate_sha256(document.get("backup_sha256", ""))
    validate_sha256(document.get("xattrs_sha256", ""))
    validate_sha256(document.get("host_fingerprint", ""))
    validate_sha256(document.get("service_unit_fingerprint", ""))
    validated_package_versions(document.get("package_versions"))
    if set(collector) != {"path", "sha256", "device", "inode"}:
        raise TransactionError("invalid_manifest", "transaction manifest is invalid")
    absolute_path(collector.get("path"), "manifest collector binary")
    validate_sha256(collector.get("sha256", ""))
    if any(
        not isinstance(collector.get(key), int)
        or isinstance(collector.get(key), bool)
        or collector[key] < 0
        for key in ("device", "inode")
    ):
        raise TransactionError("invalid_manifest", "transaction manifest is invalid")
    for key in ("uid", "gid", "mode"):
        if not isinstance(metadata.get(key), int) or isinstance(
            metadata.get(key), bool
        ):
            raise TransactionError(
                "invalid_manifest", "transaction manifest metadata is invalid"
            )
    if (
        metadata["uid"] != os.geteuid()
        or metadata["gid"] < 0
        or not 0 <= metadata["mode"] <= 0o7777
        or metadata["mode"] & 0o022
    ):
        raise TransactionError(
            "invalid_manifest", "transaction manifest metadata is invalid"
        )
    return document


def _load_private_json(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    payload, metadata = read_regular_file(
        path, label=label, max_bytes=MAX_MANIFEST_BYTES
    )
    _validate_private_file(metadata, label)
    try:
        document = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TransactionError("invalid_manifest", f"{label} is invalid JSON") from exc
    if not isinstance(document, dict):
        raise TransactionError("invalid_manifest", f"{label} is invalid")
    return document, payload


def load_manifest(path: Path) -> dict[str, Any]:
    document, _ = _load_private_json(path, label="transaction manifest")
    return validate_manifest(document, path)


def _current_path(state_root: Path) -> Path:
    return state_root / CURRENT_FILE_NAME


def _load_current(state_root: Path, *, required: bool) -> dict[str, Any] | None:
    path = _current_path(state_root)
    try:
        os.lstat(path)
    except FileNotFoundError:
        if required:
            raise TransactionError(
                "current_generation_missing", "current transaction ownership is missing"
            )
        return None
    document, _ = _load_private_json(path, label="current transaction ownership")
    if document.get("schema_version") != CURRENT_SCHEMA_VERSION:
        raise TransactionError(
            "invalid_manifest", "current transaction ownership is invalid"
        )
    generation = document.get("generation")
    if not isinstance(generation, str) or not GENERATION_RE.fullmatch(generation):
        raise TransactionError(
            "invalid_manifest", "current transaction ownership is invalid"
        )
    manifest_path = absolute_path(document.get("manifest_path"), "current manifest")
    journal_path = absolute_path(document.get("journal_path"), "current journal")
    if (
        manifest_path != state_root / f"transaction-{generation}" / "manifest.json"
        or journal_path != state_root / f"transaction-{generation}" / "journal.json"
    ):
        raise TransactionError(
            "invalid_manifest", "current transaction ownership is invalid"
        )
    validate_sha256(document.get("manifest_sha256", ""))
    return document


def _load_journal(document: Mapping[str, Any]) -> dict[str, Any]:
    journal_path = _manifest_path(document, "journal_path")
    journal, _ = _load_private_json(journal_path, label="transaction journal")
    if (
        journal.get("schema_version") != JOURNAL_SCHEMA_VERSION
        or journal.get("generation") != document.get("generation")
        or journal.get("phase") not in ALL_PHASES
        or not isinstance(journal.get("updated_at"), str)
    ):
        raise TransactionError("invalid_manifest", "transaction journal is invalid")
    return journal


def _require_current_ownership(document: Mapping[str, Any]) -> None:
    state_root = _manifest_path(document, "state_root")
    manifest_path = _manifest_path(document, "state_dir") / "manifest.json"
    current = _load_current(state_root, required=True)
    assert current is not None
    manifest_payload, manifest_metadata = read_regular_file(
        manifest_path, label="transaction manifest", max_bytes=MAX_MANIFEST_BYTES
    )
    _validate_private_file(manifest_metadata, "transaction manifest")
    if (
        current.get("generation") != document.get("generation")
        or current.get("manifest_path") != str(manifest_path)
        or current.get("journal_path") != document.get("journal_path")
        or not hmac.compare_digest(
            str(current.get("manifest_sha256")), sha256_bytes(manifest_payload)
        )
    ):
        raise TransactionError(
            "stale_transaction", "transaction is not the current generation"
        )


def _assert_current_complete_or_absent(state_root: Path) -> None:
    current = _load_current(state_root, required=False)
    if current is None:
        return
    manifest_path = absolute_path(current["manifest_path"], "current manifest")
    document = load_manifest(manifest_path)
    _require_current_ownership(document)
    phase = _load_journal(document)["phase"]
    if phase not in TERMINAL_PHASES:
        raise TransactionError(
            "recovery_required",
            "an incomplete current transaction must be restored before a new apply",
        )


def _install_current_ownership(
    document: Mapping[str, Any], manifest_payload: bytes
) -> None:
    state_root = _manifest_path(document, "state_root")
    current = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "generation": document["generation"],
        "manifest_path": str(_manifest_path(document, "state_dir") / "manifest.json"),
        "manifest_sha256": sha256_bytes(manifest_payload),
        "journal_path": document["journal_path"],
    }
    write_atomic_private(
        _current_path(state_root),
        manifest_bytes(current),
        label="current transaction ownership",
    )


def after_checkpoint(_phase: str) -> None:
    """Test seam for interruption immediately after a durable checkpoint."""


def _transition_allowed(current: str, target: str) -> bool:
    if current == target:
        return True
    if target == "restore_started" and current in APPLY_PHASES:
        return True
    if target == "recovery_required" and current != "restored":
        return True
    if current == "recovery_required" and target == "restore_config_restored":
        return True
    if current in APPLY_PHASES and target in APPLY_PHASES:
        return APPLY_PHASES.index(target) == APPLY_PHASES.index(current) + 1
    if current in RESTORE_PHASES and target in RESTORE_PHASES:
        return RESTORE_PHASE_INDEX[target] == RESTORE_PHASE_INDEX[current] + 1
    return False


def checkpoint(document: Mapping[str, Any], phase: str) -> None:
    if phase not in ALL_PHASES:
        raise TransactionError("internal_error", "transaction phase is invalid")
    _require_current_ownership(document)
    journal = _load_journal(document)
    current = journal["phase"]
    if not _transition_allowed(current, phase):
        raise TransactionError(
            "journal_state_mismatch", "transaction journal transition is invalid"
        )
    if current != phase:
        updated = {
            "schema_version": JOURNAL_SCHEMA_VERSION,
            "generation": document["generation"],
            "phase": phase,
            "updated_at": utc_now(),
        }
        write_atomic_private(
            _manifest_path(document, "journal_path"),
            manifest_bytes(updated),
            label="transaction journal",
        )
    after_checkpoint(phase)


def _load_xattr_snapshot(document: Mapping[str, Any]) -> dict[str, bytes]:
    path = _manifest_path(document, "xattrs_path")
    payload, metadata = read_regular_file(
        path, label="extended-attribute snapshot", max_bytes=MAX_XATTR_BYTES * 2
    )
    _validate_private_file(metadata, "extended-attribute snapshot")
    if not hmac.compare_digest(
        sha256_bytes(payload), validate_sha256(document.get("xattrs_sha256", ""))
    ):
        raise TransactionError(
            "metadata_hash_mismatch",
            "extended-attribute snapshot SHA-256 does not match",
        )
    return decode_xattrs(payload)


def _verify_runtime_provenance(
    document: Mapping[str, Any],
    systemctl: str,
    *,
    expected_active_state: str | None = None,
    expected_unit_file_state: str | None = None,
) -> dict[str, str]:
    if not hmac.compare_digest(
        host_fingerprint(), validate_sha256(document.get("host_fingerprint", ""))
    ):
        raise TransactionError("host_drift", "transaction belongs to another host")
    expected_packages = validated_package_versions(document.get("package_versions"))
    if validated_package_versions(package_versions()) != expected_packages:
        raise TransactionError(
            "package_version_drift", "required package versions changed"
        )
    collector = document["collector_binary"]
    collector_binary_provenance(
        absolute_path(collector["path"], "collector binary"),
        collector["sha256"],
        expected_device=collector["device"],
        expected_inode=collector["inode"],
    )
    service = document["service"]["name"]
    return revalidate_unit(
        systemctl,
        service,
        document["service_unit_fingerprint"],
        expected_active_state=expected_active_state,
        expected_unit_file_state=expected_unit_file_state,
    )


def before_provenance_check(_boundary: str) -> None:
    """Test seam for a race immediately before an apply provenance check."""


def verify_apply_provenance_boundary(
    document: Mapping[str, Any], systemctl: str, boundary: str
) -> dict[str, str]:
    before_provenance_check(boundary)
    service = document["service"]
    return _verify_runtime_provenance(
        document,
        systemctl,
        expected_active_state=service["active_state"],
        expected_unit_file_state=service["unit_file_state"],
    )


def _restore_phase_at_least(current: str, expected: str) -> bool:
    return current in RESTORE_PHASE_INDEX and (
        RESTORE_PHASE_INDEX[current] >= RESTORE_PHASE_INDEX[expected]
    )


def _restore_verified_config(document: Mapping[str, Any], *, explicit: bool) -> str:
    _require_current_ownership(document)
    backup_path = _manifest_path(document, "backup_path")
    live_path = _manifest_path(document, "live_path")
    assert_root_owned_secure_path(live_path, label="live config", include_final=True)
    backup, backup_metadata = read_regular_file(
        backup_path, label="transaction backup", max_bytes=MAX_CONFIG_BYTES
    )
    _validate_private_file(backup_metadata, "transaction backup")
    expected_backup_sha = validate_sha256(str(document["backup_sha256"]))
    actual_backup_sha = sha256_bytes(backup)
    if not hmac.compare_digest(actual_backup_sha, expected_backup_sha):
        raise TransactionError(
            "backup_hash_mismatch", "transaction backup SHA-256 does not match"
        )
    expected_xattrs = _load_xattr_snapshot(document)
    if explicit and not hmac.compare_digest(
        host_fingerprint(), validate_sha256(document.get("host_fingerprint", ""))
    ):
        raise TransactionError("host_drift", "transaction belongs to another host")

    current_live, current_metadata = read_regular_file(
        live_path, label="live config", max_bytes=MAX_CONFIG_BYTES
    )
    current_sha = sha256_bytes(current_live)
    staged_sha = validate_sha256(str(document["staged_sha256"]))
    live_is_staged = hmac.compare_digest(current_sha, staged_sha)
    live_is_backup = hmac.compare_digest(current_sha, expected_backup_sha)
    if explicit and not (live_is_staged or live_is_backup):
        raise TransactionError(
            "live_config_drift",
            "live config matches neither this transaction's staged nor backup SHA-256",
        )

    journal = _load_journal(document)
    phase = journal["phase"]
    if phase == "recovery_required" and not live_is_backup:
        raise TransactionError(
            "journal_state_mismatch",
            "recovery-required journal phase conflicts with live config",
        )
    if _restore_phase_at_least(phase, "restore_config_restored") and not live_is_backup:
        raise TransactionError(
            "journal_state_mismatch",
            "restored journal phase conflicts with live config",
        )
    if phase in APPLY_PHASES:
        checkpoint(document, "restore_started")
        phase = "restore_started"

    live_metadata = document["live_metadata"]
    if phase != "recovery_required" and not _restore_phase_at_least(
        phase, "restore_config_restored"
    ):
        if phase != "restore_config_pending":
            checkpoint(document, "restore_config_pending")
        current_xattrs = read_xattrs(live_path, current_metadata, label="live config")
        metadata_matches = (
            current_metadata.st_uid == live_metadata["uid"]
            and current_metadata.st_gid == live_metadata["gid"]
            and stat.S_IMODE(current_metadata.st_mode) == live_metadata["mode"]
            and current_xattrs == expected_xattrs
        )
        if not live_is_backup or not metadata_matches:
            atomic_install(
                live_path,
                backup,
                uid=live_metadata["uid"],
                gid=live_metadata["gid"],
                mode=live_metadata["mode"],
                xattrs=expected_xattrs,
            )
        verify_installed_file(
            live_path,
            backup,
            uid=live_metadata["uid"],
            gid=live_metadata["gid"],
            mode=live_metadata["mode"],
            label="restored live config",
            xattrs=expected_xattrs,
        )
        checkpoint(document, "restore_config_restored")
    else:
        current_xattrs = read_xattrs(live_path, current_metadata, label="live config")
        metadata_matches = (
            current_metadata.st_uid == live_metadata["uid"]
            and current_metadata.st_gid == live_metadata["gid"]
            and stat.S_IMODE(current_metadata.st_mode) == live_metadata["mode"]
            and current_xattrs == expected_xattrs
        )
        if not metadata_matches:
            atomic_install(
                live_path,
                backup,
                uid=live_metadata["uid"],
                gid=live_metadata["gid"],
                mode=live_metadata["mode"],
                xattrs=expected_xattrs,
            )
        verify_installed_file(
            live_path,
            backup,
            uid=live_metadata["uid"],
            gid=live_metadata["gid"],
            mode=live_metadata["mode"],
            label="restored live config",
            xattrs=expected_xattrs,
        )
        if phase == "recovery_required":
            checkpoint(document, "restore_config_restored")
    return actual_backup_sha


def _raise_recovery_required(
    document: Mapping[str, Any], cause: TransactionError
) -> None:
    phase = _load_journal(document)["phase"]
    if phase != "restored" and phase != "recovery_required":
        checkpoint(document, "recovery_required")
    error = TransactionError(
        "recovery_required",
        "verified config bytes were restored; runtime recovery is required",
    )
    error.config_restored = True  # type: ignore[attr-defined]
    error.cause_code = cause.code  # type: ignore[attr-defined]
    raise error from cause


def _restore_service_action(
    document: Mapping[str, Any],
    *,
    systemctl: str,
    pending_phase: str,
    done_phase: str,
    action: str,
) -> None:
    phase = _load_journal(document)["phase"]
    service = document["service"]
    name = service["name"]
    target_active_state: str | None = None
    target_unit_file_state: str | None = None
    if action == "enable":
        target_unit_file_state = "enabled"
    elif action == "disable":
        target_unit_file_state = "disabled"
    elif action == "restart":
        target_active_state = "active"
        target_unit_file_state = service["unit_file_state"]
    elif action == "stop":
        target_active_state = "inactive"
        target_unit_file_state = service["unit_file_state"]
    if _restore_phase_at_least(phase, done_phase):
        revalidate_unit(
            systemctl,
            name,
            document["service_unit_fingerprint"],
            expected_active_state=target_active_state,
            expected_unit_file_state=target_unit_file_state,
        )
        return
    if phase != pending_phase:
        checkpoint(document, pending_phase)
    before = revalidate_unit(systemctl, name, document["service_unit_fingerprint"])
    service_action(systemctl, action, name)
    expected_active_state = before["active_state"]
    expected_unit_file_state = before["unit_file_state"]
    if target_active_state is not None:
        expected_active_state = target_active_state
    if target_unit_file_state is not None:
        expected_unit_file_state = target_unit_file_state
    revalidate_unit(
        systemctl,
        name,
        document["service_unit_fingerprint"],
        expected_active_state=expected_active_state,
        expected_unit_file_state=expected_unit_file_state,
    )
    checkpoint(document, done_phase)


def _verify_restored_terminal_state(
    document: Mapping[str, Any], systemctl: str
) -> dict[str, Any]:
    service = document["service"]
    name = service["name"]
    revalidate_unit(
        systemctl,
        name,
        document["service_unit_fingerprint"],
        expected_active_state=service["active_state"],
        expected_unit_file_state=service["unit_file_state"],
    )
    if service["active_state"] == "active":
        health = wait_for_health(
            document["health"]["url"], document["health"]["timeout_seconds"]
        )
        revalidate_unit(
            systemctl,
            name,
            document["service_unit_fingerprint"],
            expected_active_state=service["active_state"],
            expected_unit_file_state=service["unit_file_state"],
        )
        return health
    return {"checked": False, "ok": True}


def _restore_service_state(
    document: Mapping[str, Any], systemctl: str
) -> dict[str, Any]:
    service = document["service"]
    _restore_service_action(
        document,
        systemctl=systemctl,
        pending_phase="restore_daemon_reload_pending",
        done_phase="restore_daemon_reload_done",
        action="daemon-reload",
    )
    _restore_service_action(
        document,
        systemctl=systemctl,
        pending_phase="restore_enablement_pending",
        done_phase="restore_enablement_done",
        action="enable" if service["unit_file_state"] == "enabled" else "disable",
    )
    _restore_service_action(
        document,
        systemctl=systemctl,
        pending_phase="restore_active_pending",
        done_phase="restore_active_done",
        action="restart" if service["active_state"] == "active" else "stop",
    )

    phase = _load_journal(document)["phase"]
    health: dict[str, Any] = {"checked": False, "ok": True}
    if phase == "restored":
        return _verify_restored_terminal_state(document, systemctl)
    if phase != "restore_health_pending":
        checkpoint(document, "restore_health_pending")
    revalidate_unit(
        systemctl,
        service["name"],
        document["service_unit_fingerprint"],
        expected_active_state=service["active_state"],
        expected_unit_file_state=service["unit_file_state"],
    )
    if service["active_state"] == "active":
        health = wait_for_health(
            document["health"]["url"], document["health"]["timeout_seconds"]
        )
    revalidate_unit(
        systemctl,
        service["name"],
        document["service_unit_fingerprint"],
        expected_active_state=service["active_state"],
        expected_unit_file_state=service["unit_file_state"],
    )
    checkpoint(document, "restored")
    return health


def restore_from_document(
    document: Mapping[str, Any], *, explicit: bool
) -> dict[str, Any]:
    actual_backup_sha = _restore_verified_config(document, explicit=explicit)
    try:
        systemctl = systemctl_path()
        _verify_runtime_provenance(document, systemctl)
        health = _restore_service_state(document, systemctl)
    except TransactionError as cause:
        if cause.code in RUNTIME_RECOVERY_CODES:
            _raise_recovery_required(document, cause)
        raise
    service = document["service"]
    return {
        "status": "restored",
        "backup_sha256": actual_backup_sha,
        "generation": document["generation"],
        "service": {
            "name": service["name"],
            "active_state_restored": service["active_state"],
            "unit_file_state_restored": service["unit_file_state"],
            "active_restored": service["active_state"] == "active",
            "enabled_restored": service["unit_file_state"] == "enabled",
        },
        "health": health,
    }


def _raise_apply_failure(
    original: BaseException,
    *,
    rollback: Mapping[str, Any],
    manifest_path: Path,
) -> None:
    if isinstance(original, TransactionError):
        original.rollback = dict(rollback)  # type: ignore[attr-defined]
        original.manifest_path = str(manifest_path)  # type: ignore[attr-defined]
        raise original
    if isinstance(original, (KeyboardInterrupt, SystemExit)):
        error = TransactionError(
            "interrupted", "collector config apply was interrupted"
        )
    else:
        error = TransactionError("apply_failed", "collector config apply failed")
    error.rollback = dict(rollback)  # type: ignore[attr-defined]
    error.manifest_path = str(manifest_path)  # type: ignore[attr-defined]
    raise error from original


def apply_transaction(args: argparse.Namespace) -> dict[str, Any]:
    staged_path = absolute_path(args.staged, "staged config")
    live_path = absolute_path(args.live, "live config")
    state_root = absolute_path(args.state_root, "state root")
    collector_path = absolute_path(args.collector_binary, "collector binary")
    if staged_path == live_path:
        raise TransactionError(
            "invalid_path", "staged and live config paths must differ"
        )
    if state_root in staged_path.parents or state_root in live_path.parents:
        raise TransactionError(
            "invalid_path", "state root must not contain staged or live config paths"
        )
    service = validate_service_name(args.service)
    health_url = validate_loopback_health_url(args.health_url)
    expected_sha256 = validate_sha256(args.expected_sha256)
    expected_live_sha256 = getattr(args, "expected_live_sha256", None)
    if expected_live_sha256 is not None:
        expected_live_sha256 = validate_sha256(expected_live_sha256)
    private_artifact = bool(getattr(args, "private_artifact", False))
    expected_binary_sha256 = validate_sha256(args.collector_binary_sha256)
    health_timeout = validate_timeout(args.health_timeout)

    staged, staged_metadata = read_regular_file(
        staged_path, label="staged config", max_bytes=MAX_CONFIG_BYTES
    )
    staged_sha256 = sha256_bytes(staged)
    if private_artifact:
        validate_private_artifact_metadata(staged_metadata, label="staged artifact")
    if not hmac.compare_digest(staged_sha256, expected_sha256):
        raise TransactionError(
            "staged_hash_mismatch", "staged config SHA-256 does not match"
        )
    assert_root_owned_secure_path(live_path, label="live config", include_final=True)
    assert_root_owned_secure_path(
        state_root.parent, label="state root parent", include_final=True
    )
    ensure_state_root(state_root)
    with acquire_lock(state_root):
        _assert_current_complete_or_absent(state_root)
        staged_again, staged_again_metadata = read_regular_file(
            staged_path, label="staged config", max_bytes=MAX_CONFIG_BYTES
        )
        if (
            not hmac.compare_digest(sha256_bytes(staged_again), staged_sha256)
            or staged_again_metadata.st_dev != staged_metadata.st_dev
            or staged_again_metadata.st_ino != staged_metadata.st_ino
            or staged_again_metadata.st_size != staged_metadata.st_size
            or staged_again_metadata.st_mtime_ns != staged_metadata.st_mtime_ns
            or staged_again_metadata.st_uid != staged_metadata.st_uid
            or staged_again_metadata.st_gid != staged_metadata.st_gid
            or stat.S_IMODE(staged_again_metadata.st_mode)
            != stat.S_IMODE(staged_metadata.st_mode)
        ):
            raise TransactionError("file_changed", "staged config changed before apply")
        if private_artifact:
            validate_private_artifact_metadata(
                staged_again_metadata, label="staged artifact"
            )
        live, live_metadata = read_regular_file(
            live_path, label="live config", max_bytes=MAX_CONFIG_BYTES
        )
        if private_artifact:
            validate_private_artifact_metadata(live_metadata, label="live artifact")
        if (
            live_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(live_metadata.st_mode) & 0o022
        ):
            raise TransactionError(
                "unsafe_file",
                "live config must be root-owned and not group/other-writable",
            )
        live_xattrs = read_xattrs(live_path, live_metadata, label="live config")
        live_sha256 = sha256_bytes(live)
        if expected_live_sha256 is not None and not hmac.compare_digest(
            live_sha256, expected_live_sha256
        ):
            raise TransactionError(
                "live_hash_mismatch", "live file SHA-256 does not match"
            )

        systemctl = systemctl_path()
        metadata = service_state_snapshot(systemctl, service)
        active_state = metadata["active_state"]
        unit_file_state = metadata["unit_file_state"]
        unit_fingerprint = service_unit_fingerprint(systemctl, service)
        packages = validated_package_versions(package_versions())
        host_id = host_fingerprint()
        collector = collector_binary_provenance(collector_path, expected_binary_sha256)
        was_active = active_state == "active"
        was_enabled = unit_file_state == "enabled"

        generation = secrets.token_hex(16)
        state_dir = create_state_dir(state_root, generation)
        backup_path = state_dir / "live-config.backup"
        xattrs_path = state_dir / "live-config.xattrs.json"
        journal_path = state_dir / "journal.json"
        manifest_path = state_dir / "manifest.json"
        xattrs_payload = encode_xattrs(live_xattrs)
        write_exclusive(backup_path, live, mode=0o600, label="transaction backup")
        write_exclusive(
            xattrs_path,
            xattrs_payload,
            mode=0o600,
            label="extended-attribute snapshot",
        )
        document = snapshot_manifest(
            generation=generation,
            state_root=state_root,
            state_dir=state_dir,
            backup_path=backup_path,
            xattrs_path=xattrs_path,
            xattrs_sha256=sha256_bytes(xattrs_payload),
            journal_path=journal_path,
            staged_path=staged_path,
            live_path=live_path,
            staged_sha256=staged_sha256,
            live_sha256=live_sha256,
            live_metadata=live_metadata,
            service=service,
            health_url=health_url,
            health_timeout=health_timeout,
            active_state=active_state,
            unit_file_state=unit_file_state,
            metadata=metadata,
            packages=packages,
            host_id=host_id,
            collector_binary=collector,
            unit_fingerprint=unit_fingerprint,
        )
        manifest_payload = manifest_bytes(document)
        write_exclusive(
            manifest_path,
            manifest_payload,
            mode=0o600,
            label="transaction manifest",
        )
        initial_journal = {
            "schema_version": JOURNAL_SCHEMA_VERSION,
            "generation": generation,
            "phase": "prepared",
            "updated_at": utc_now(),
        }
        write_exclusive(
            journal_path,
            manifest_bytes(initial_journal),
            mode=0o600,
            label="transaction journal",
        )
        _install_current_ownership(document, manifest_payload)

        health: dict[str, Any] = {"checked": False, "ok": True}
        try:
            after_checkpoint("prepared")
            current_live, current_metadata = read_regular_file(
                live_path, label="live config", max_bytes=MAX_CONFIG_BYTES
            )
            current_xattrs = read_xattrs(
                live_path, current_metadata, label="live config"
            )
            current_staged, current_staged_metadata = read_regular_file(
                staged_path, label="staged config", max_bytes=MAX_CONFIG_BYTES
            )
            if (
                not hmac.compare_digest(sha256_bytes(current_live), live_sha256)
                or current_metadata.st_dev != live_metadata.st_dev
                or current_metadata.st_ino != live_metadata.st_ino
                or current_metadata.st_uid != live_metadata.st_uid
                or current_metadata.st_gid != live_metadata.st_gid
                or stat.S_IMODE(current_metadata.st_mode)
                != stat.S_IMODE(live_metadata.st_mode)
                or current_xattrs != live_xattrs
                or not hmac.compare_digest(sha256_bytes(current_staged), staged_sha256)
                or current_staged_metadata.st_dev != staged_metadata.st_dev
                or current_staged_metadata.st_ino != staged_metadata.st_ino
                or current_staged_metadata.st_uid != staged_metadata.st_uid
                or current_staged_metadata.st_gid != staged_metadata.st_gid
                or stat.S_IMODE(current_staged_metadata.st_mode)
                != stat.S_IMODE(staged_metadata.st_mode)
            ):
                raise TransactionError(
                    "live_config_changed",
                    "staged or live config changed during snapshot",
                )
            if private_artifact:
                validate_private_artifact_metadata(
                    current_staged_metadata, label="staged artifact"
                )
            checkpoint(document, "apply_install_pending")
            verify_apply_provenance_boundary(document, systemctl, "before_install")
            atomic_install(
                live_path,
                staged,
                uid=live_metadata.st_uid,
                gid=live_metadata.st_gid,
                mode=stat.S_IMODE(live_metadata.st_mode),
                xattrs=live_xattrs,
            )
            verify_installed_file(
                live_path,
                staged,
                uid=live_metadata.st_uid,
                gid=live_metadata.st_gid,
                mode=stat.S_IMODE(live_metadata.st_mode),
                label="installed live config",
                xattrs=live_xattrs,
            )
            checkpoint(document, "apply_config_installed")
            checkpoint(document, "apply_restart_pending")
            verify_apply_provenance_boundary(document, systemctl, "before_restart")
            if was_active:
                service_action(systemctl, "restart", service)
            verify_apply_provenance_boundary(document, systemctl, "after_restart")
            checkpoint(document, "apply_service_restarted")
            checkpoint(document, "apply_health_pending")
            verify_apply_provenance_boundary(document, systemctl, "before_health")
            if was_active:
                health = wait_for_health(health_url, health_timeout)
            verify_apply_provenance_boundary(document, systemctl, "after_health")
            verify_apply_provenance_boundary(document, systemctl, "before_applied")
            checkpoint(document, "applied")
        except BaseException as original:
            try:
                restored = restore_from_document(document, explicit=False)
                rollback: dict[str, Any] = {
                    "attempted": True,
                    "ok": True,
                    "health": restored["health"],
                }
            except TransactionError as recovery_failure:
                if recovery_failure.code == "recovery_required" and getattr(
                    recovery_failure, "config_restored", False
                ):
                    rollback = {
                        "attempted": True,
                        "ok": False,
                        "config_restored": True,
                        "service_state_restored": False,
                        "recovery_required": True,
                    }
                    recovery_failure.rollback = rollback  # type: ignore[attr-defined]
                    recovery_failure.manifest_path = str(  # type: ignore[attr-defined]
                        manifest_path
                    )
                    raise recovery_failure from original
                rollback = {"attempted": True, "ok": False}
            except BaseException:
                rollback = {"attempted": True, "ok": False}
            _raise_apply_failure(
                original, rollback=rollback, manifest_path=manifest_path
            )

        return {
            "ok": True,
            "operation": "apply",
            "status": "applied",
            "manifest": str(manifest_path),
            "generation": generation,
            "staged_sha256": staged_sha256,
            "previous_live_sha256": live_sha256,
            "service": {
                "name": service,
                "was_active": was_active,
                "was_enabled": was_enabled,
                "restarted": was_active,
            },
            "health": health,
        }


def restore_transaction(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = absolute_path(args.manifest, "transaction manifest")
    first_document = load_manifest(manifest_path)
    state_root = _manifest_path(first_document, "state_root")
    with acquire_lock(state_root):
        document = load_manifest(manifest_path)
        if document != first_document:
            raise TransactionError(
                "manifest_changed", "transaction manifest changed while locking"
            )
        _require_current_ownership(document)
        try:
            restored = restore_from_document(document, explicit=True)
        except TransactionError as error:
            if error.code == "recovery_required" and getattr(
                error, "config_restored", False
            ):
                error.manifest_path = str(manifest_path)  # type: ignore[attr-defined]
                error.rollback = {  # type: ignore[attr-defined]
                    "attempted": True,
                    "ok": False,
                    "config_restored": True,
                    "service_state_restored": False,
                    "recovery_required": True,
                }
            raise
    return {
        "ok": True,
        "operation": "restore",
        "manifest": str(manifest_path),
        **restored,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)

    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--staged", required=True)
    apply_parser.add_argument("--live", required=True)
    apply_parser.add_argument("--service", required=True)
    apply_parser.add_argument("--health-url", required=True)
    apply_parser.add_argument("--expected-sha256", required=True)
    apply_parser.add_argument("--expected-live-sha256")
    apply_parser.add_argument("--private-artifact", action="store_true")
    apply_parser.add_argument("--collector-binary", required=True)
    apply_parser.add_argument("--collector-binary-sha256", required=True)
    apply_parser.add_argument("--state-root", required=True)
    apply_parser.add_argument(
        "--health-timeout", type=float, default=DEFAULT_HEALTH_TIMEOUT_SECONDS
    )

    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("--manifest", required=True)
    return parser


def _transaction_signal_handler(_signum: int, _frame: Any) -> None:
    raise TransactionError("interrupted", "transaction interrupted by signal")


def install_signal_handlers() -> dict[int, Any]:
    previous: dict[int, Any] = {}
    try:
        for signal_number in (signal.SIGINT, signal.SIGTERM):
            previous[signal_number] = signal.getsignal(signal_number)
            signal.signal(signal_number, _transaction_signal_handler)
    except (OSError, ValueError) as exc:
        for signal_number, handler in previous.items():
            signal.signal(signal_number, handler)
        raise TransactionError(
            "signal_handler_failed", "transaction signal handlers cannot be installed"
        ) from exc
    return previous


def restore_signal_handlers(previous: Mapping[int, Any]) -> None:
    for signal_number, handler in previous.items():
        signal.signal(signal_number, handler)


def main(argv: Sequence[str] | None = None) -> int:
    operation = "unknown"
    previous_handlers: dict[int, Any] = {}
    try:
        args = build_parser().parse_args(argv)
        operation = args.operation
        previous_handlers = install_signal_handlers()
        validate_runtime()
        result = (
            apply_transaction(args)
            if operation == "apply"
            else restore_transaction(args)
        )
        emit(result)
        return 0
    except TransactionError as exc:
        result: dict[str, Any] = {
            "ok": False,
            "operation": operation,
            "error": {"code": exc.code, "message": exc.safe_message},
        }
        manifest_path = getattr(exc, "manifest_path", None)
        rollback = getattr(exc, "rollback", None)
        if manifest_path is not None:
            result["manifest"] = manifest_path
        if rollback is not None:
            result["rollback"] = rollback
        emit(result, stream=sys.stderr)
        return 1
    except SystemExit:
        raise
    except BaseException:
        emit(
            {
                "ok": False,
                "operation": operation,
                "error": {
                    "code": "internal_error",
                    "message": "unexpected internal transaction failure",
                },
            },
            stream=sys.stderr,
        )
        return 1
    finally:
        if previous_handlers:
            restore_signal_handlers(previous_handlers)


if __name__ == "__main__":
    raise SystemExit(main())
