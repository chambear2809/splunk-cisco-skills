#!/usr/bin/env python3
"""Apply or restore the dedicated Galileo tinyproxy bundle transactionally.

This helper is intentionally narrow: it runs only as root on Linux, consumes a
root-private request, manages three exact paths, and changes only the generic
and dedicated tinyproxy systemd unit state.  Package installation is a pinned
preflight dependency and is never mutated.

Machine-readable output is fixed-schema sanitized JSON.  File contents,
credentials, hostnames, paths, and subprocess output are never emitted.
"""

from __future__ import annotations

import argparse
import base64
import configparser
import copy
import datetime as dt
import errno
import fcntl
import grp
import hashlib
import hmac
import ipaddress
import json
import math
import os
import pwd
import re
import secrets
import shlex
import signal
import socket
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, BinaryIO, Mapping, Sequence


REQUEST_SCHEMA = "galileo-proxy-bundle-request/v1"
STATE_SCHEMA = "galileo-proxy-bundle-state/v1"
JOURNAL_SCHEMA = "galileo-proxy-bundle-journal/v1"
CURRENT_SCHEMA = "galileo-proxy-bundle-current/v1"

ROLES = ("proxy_filter", "proxy_config", "proxy_unit")
APPLY_ORDER = ROLES
RESTORE_ORDER = tuple(reversed(ROLES))
ROLE_LIMITS = {
    "proxy_filter": 16 * 1024,
    "proxy_config": 64 * 1024,
    "proxy_unit": 256 * 1024,
}
TARGETS = {
    "proxy_filter": Path("/etc/tinyproxy/galileo.filter"),
    "proxy_config": Path("/etc/tinyproxy/galileo.conf"),
    "proxy_unit": Path("/etc/systemd/system/galileo-tinyproxy.service"),
}
ROLE_MODES = {role: 0o644 for role in ROLES}

GENERIC_UNIT = "tinyproxy.service"
DEDICATED_UNIT = "galileo-tinyproxy.service"
TINYPROXY_BINARY = Path("/usr/bin/tinyproxy")
TINYPROXY_PACKAGE = "tinyproxy"
BINARY_PACKAGES = frozenset({"tinyproxy", "tinyproxy-bin"})
PROXY_USER = "tinyproxy"
PROXY_GROUP = "tinyproxy"
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 18888
DENIED_CONNECT_HOST = "example.invalid"

MACHINE_ID_PATHS = (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id"))
SYSTEMCTL_PATHS = ("/usr/bin/systemctl", "/bin/systemctl")
SYSTEMD_ANALYZE_PATHS = ("/usr/bin/systemd-analyze", "/bin/systemd-analyze")
SS_PATHS = ("/usr/bin/ss", "/bin/ss")
DPKG_QUERY = "/usr/bin/dpkg-query"

MAX_REQUEST_BYTES = 1024 * 1024
MAX_STATE_BYTES = 2 * 1024 * 1024
MAX_BINARY_BYTES = 128 * 1024 * 1024
MAX_XATTR_COUNT = 64
MAX_XATTR_BYTES = 64 * 1024
MAX_COMMAND_OUTPUT = 32 * 1024
MAX_PROBE_TIMEOUT = 15.0

GENERATION_RE = re.compile(r"^[0-9a-f]{32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SAFE_VERSION_RE = re.compile(r"^[A-Za-z0-9.+:~_-]{1,256}$")
DNS_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
MODE_RE = re.compile(r"^0[0-7]{3}$")
HTTP_STATUS_RE = re.compile(rb"^HTTP/1\.[01] ([0-9]{3})(?:[ \t]|$)")

SUBPROCESS_ENV = {
    "LANG": "C",
    "LC_ALL": "C",
    "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
}

UNIT_EXPECTED = {
    "Unit": {
        "Description": "Dedicated exact-host egress proxy for Galileo OTLP",
        "Documentation": "https://tinyproxy.github.io/",
        "Wants": "network-online.target",
        "After": "network-online.target",
        "Before": "splunk-otel-collector.service",
    },
    "Service": {
        "Type": "simple",
        "ExecStart": "/usr/bin/tinyproxy -d -c /etc/tinyproxy/galileo.conf",
        "Restart": "on-failure",
        "RestartSec": "2s",
        "TimeoutStartSec": "15s",
        "TimeoutStopSec": "15s",
        "User": PROXY_USER,
        "Group": PROXY_GROUP,
        "RuntimeDirectory": "tinyproxy-galileo",
        "RuntimeDirectoryMode": "0755",
        "UMask": "0077",
        "NoNewPrivileges": "yes",
        "PrivateDevices": "yes",
        "PrivateTmp": "yes",
        "ProtectSystem": "strict",
        "ProtectHome": "yes",
        "ProtectKernelTunables": "yes",
        "ProtectKernelModules": "yes",
        "ProtectKernelLogs": "yes",
        "ProtectControlGroups": "yes",
        "ProtectClock": "yes",
        "ProtectHostname": "yes",
        "LockPersonality": "yes",
        "MemoryDenyWriteExecute": "yes",
        "RestrictNamespaces": "yes",
        "RestrictSUIDSGID": "yes",
        "RestrictAddressFamilies": "AF_UNIX AF_INET AF_INET6",
        "CapabilityBoundingSet": "",
        "AmbientCapabilities": "",
        "SystemCallArchitectures": "native",
        "TasksMax": "64",
        "LimitNOFILE": "1024",
        "StandardOutput": "journal",
        "StandardError": "journal",
    },
    "Install": {"WantedBy": "multi-user.target"},
}


class TransactionError(RuntimeError):
    """A public, sanitized transaction failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        rollback: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.rollback = dict(rollback) if rollback is not None else None


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise TransactionError("invalid_arguments", "command arguments are invalid")


def emit(document: Mapping[str, Any], *, stream: Any = sys.stdout) -> None:
    stream.write(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")
    stream.flush()


def utc_now() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def json_bytes(document: Mapping[str, Any]) -> bytes:
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def reject_nonfinite_json(value: str) -> None:
    raise ValueError(f"invalid JSON number: {value}")


def validate_runtime() -> None:
    if not sys.platform.startswith("linux"):
        raise TransactionError("linux_required", "proxy transactions require Linux")
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        raise TransactionError("root_required", "proxy transactions require root")


def absolute_path(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value or len(value) > 4096 or "\x00" in value:
        raise TransactionError("invalid_path", f"{label} path is invalid")
    path = Path(value)
    if not path.is_absolute() or path != Path(os.path.normpath(value)):
        raise TransactionError("invalid_path", f"{label} path must be canonical")
    return path


def validate_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise TransactionError("invalid_manifest", f"{label} SHA-256 is invalid")
    return value


def validate_nonnegative_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TransactionError("invalid_manifest", f"{label} is invalid")
    return value


def validate_mode(value: Any) -> int:
    if not isinstance(value, str) or not MODE_RE.fullmatch(value):
        raise TransactionError("invalid_manifest", "file mode is invalid")
    return int(value, 8)


def validate_timeout(value: Any) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
        or value > MAX_PROBE_TIMEOUT
    ):
        raise TransactionError(
            "invalid_manifest", "probe timeout must be positive and bounded"
        )
    return float(value)


def validate_dns_host(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 253
        or value != value.lower()
        or value.endswith(".")
        or value == DENIED_CONNECT_HOST
    ):
        raise TransactionError("invalid_manifest", "allowed proxy host is invalid")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        pass
    else:
        raise TransactionError(
            "invalid_manifest", "allowed proxy host must be a DNS name"
        )
    labels = value.split(".")
    if len(labels) < 2 or any(not DNS_LABEL_RE.fullmatch(label) for label in labels):
        raise TransactionError("invalid_manifest", "allowed proxy host is invalid")
    return value


def _path_components(path: Path) -> list[Path]:
    result: list[Path] = []
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        result.append(current)
    return result


def assert_trusted_path(
    path: Path,
    *,
    label: str,
    owner_uid: int,
    include_final: bool,
    allow_missing_final: bool = False,
) -> None:
    components = [Path(path.anchor), *_path_components(path)]
    final_index = len(components) - 1
    for index, component in enumerate(components):
        if index == final_index and not include_final:
            break
        try:
            info = os.lstat(component)
        except FileNotFoundError as exc:
            if allow_missing_final and index == final_index:
                return
            raise TransactionError(
                "unsafe_path", f"{label} path does not exist"
            ) from exc
        except OSError as exc:
            raise TransactionError(
                "unsafe_path", f"{label} path is inaccessible"
            ) from exc
        if stat.S_ISLNK(info.st_mode):
            raise TransactionError("unsafe_path", f"{label} path contains a symlink")
        if index < final_index and not stat.S_ISDIR(info.st_mode):
            raise TransactionError(
                "unsafe_path", f"{label} ancestor is not a directory"
            )
        if info.st_uid not in {0, owner_uid} or stat.S_IMODE(info.st_mode) & 0o022:
            raise TransactionError(
                "unsafe_path",
                f"{label} ancestry must be trusted and not group/other-writable",
            )


def assert_private_directory(path: Path, *, owner_uid: int, label: str) -> None:
    assert_trusted_path(path, label=label, owner_uid=owner_uid, include_final=True)
    info = os.lstat(path)
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != owner_uid
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise TransactionError("unsafe_directory", f"{label} must be mode 0700")


def fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise TransactionError(
            "fsync_failed", "transaction state was not durable"
        ) from exc


def ensure_state_root(path: Path, *, owner_uid: int) -> None:
    assert_trusted_path(
        path.parent,
        label="state-root parent",
        owner_uid=owner_uid,
        include_final=True,
    )
    created = False
    try:
        os.mkdir(path, 0o700)
        created = True
    except FileExistsError:
        pass
    except OSError as exc:
        raise TransactionError(
            "state_root_failed", "state root could not be created"
        ) from exc
    if created:
        os.chmod(path, 0o700, follow_symlinks=False)
        fsync_directory(path.parent)
    assert_private_directory(path, owner_uid=owner_uid, label="state root")


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    offset = 0
    while offset < len(view):
        written = os.write(descriptor, view[offset:])
        if written <= 0:
            raise OSError("short write")
        offset += written


def write_exclusive(
    path: Path,
    payload: bytes,
    *,
    mode: int,
    owner_uid: int,
    owner_gid: int,
) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags, mode)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise TransactionError(
                    "unsafe_file", "transaction state file is unsafe"
                )
            os.fchown(descriptor, owner_uid, owner_gid)
            os.fchmod(descriptor, mode)
            _write_all(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        fsync_directory(path.parent)
    except TransactionError:
        raise
    except OSError as exc:
        raise TransactionError(
            "state_write_failed", "transaction state write failed"
        ) from exc


def write_atomic_private(
    path: Path, payload: bytes, *, owner_uid: int, owner_gid: int
) -> None:
    assert_private_directory(path.parent, owner_uid=owner_uid, label="state directory")
    try:
        existing = os.lstat(path)
    except FileNotFoundError:
        existing = None
    if existing is not None and (
        not stat.S_ISREG(existing.st_mode)
        or existing.st_nlink != 1
        or existing.st_uid != owner_uid
        or stat.S_IMODE(existing.st_mode) != 0o600
    ):
        raise TransactionError("unsafe_file", "transaction state file is unsafe")
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent
        )
    except OSError as exc:
        raise TransactionError(
            "state_write_failed", "transaction state write failed"
        ) from exc
    temporary = Path(temporary_name)
    installed = False
    try:
        os.fchown(descriptor, owner_uid, owner_gid)
        os.fchmod(descriptor, 0o600)
        _write_all(descriptor, payload)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path)
        installed = True
        fsync_directory(path.parent)
    except OSError as exc:
        raise TransactionError(
            "state_write_failed", "transaction state write failed"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if not installed:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def _safe_open_regular(
    path: Path, *, label: str, owner_uid: int
) -> tuple[int, os.stat_result]:
    assert_trusted_path(path, label=label, owner_uid=owner_uid, include_final=False)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise TransactionError(
            "unsafe_file", f"{label} cannot be opened safely"
        ) from exc
    try:
        opened = os.fstat(descriptor)
        named = os.lstat(path)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or stat.S_ISLNK(named.st_mode)
            or opened.st_dev != named.st_dev
            or opened.st_ino != named.st_ino
        ):
            raise TransactionError("unsafe_file", f"{label} must be a single-link file")
        return descriptor, opened
    except BaseException:
        os.close(descriptor)
        raise


def read_regular_file(
    path: Path, *, label: str, max_bytes: int, owner_uid: int
) -> tuple[bytes, os.stat_result]:
    descriptor, before = _safe_open_regular(path, label=label, owner_uid=owner_uid)
    try:
        if before.st_size < 0 or before.st_size > max_bytes:
            raise TransactionError("file_too_large", f"{label} exceeds the size limit")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        after = os.fstat(descriptor)
        if len(payload) > max_bytes:
            raise TransactionError("file_too_large", f"{label} exceeds the size limit")
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise TransactionError("file_changed", f"{label} changed while being read")
        return payload, before
    finally:
        os.close(descriptor)


def read_private_json(
    path: Path, *, label: str, max_bytes: int, owner_uid: int
) -> tuple[dict[str, Any], bytes, os.stat_result]:
    payload, info = read_regular_file(
        path, label=label, max_bytes=max_bytes, owner_uid=owner_uid
    )
    if info.st_uid != owner_uid or stat.S_IMODE(info.st_mode) != 0o600:
        raise TransactionError("unsafe_file", f"{label} must be mode 0600")
    try:
        document = json.loads(
            payload.decode("utf-8", errors="strict"),
            parse_constant=reject_nonfinite_json,
        )
    except (
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
        RecursionError,
    ) as exc:
        raise TransactionError("invalid_manifest", f"{label} is invalid JSON") from exc
    if not isinstance(document, dict):
        raise TransactionError("invalid_manifest", f"{label} must be an object")
    return document, payload, info


def read_xattrs(path: Path, info: os.stat_result, *, label: str) -> dict[str, bytes]:
    if not all(callable(getattr(os, name, None)) for name in ("listxattr", "getxattr")):
        if sys.platform.startswith("linux"):
            raise TransactionError(
                "metadata_unsupported", "extended attributes are required"
            )
        return {}
    try:
        names = os.listxattr(path, follow_symlinks=False)
    except OSError as exc:
        if exc.errno in {errno.ENOTSUP, getattr(errno, "EOPNOTSUPP", errno.ENOTSUP)}:
            return {}
        raise TransactionError(
            "metadata_read_failed", f"{label} metadata is unavailable"
        ) from exc
    if not isinstance(names, list) or len(names) > MAX_XATTR_COUNT:
        raise TransactionError("metadata_too_large", f"{label} has excessive metadata")
    captured: dict[str, bytes] = {}
    total = 0
    for name in sorted(names):
        if not isinstance(name, str) or not name or len(name.encode()) > 255:
            raise TransactionError("metadata_invalid", f"{label} metadata is invalid")
        try:
            value = os.getxattr(path, name, follow_symlinks=False)
        except OSError as exc:
            raise TransactionError(
                "metadata_read_failed", f"{label} metadata changed"
            ) from exc
        total += len(name.encode()) + len(value)
        if total > MAX_XATTR_BYTES:
            raise TransactionError(
                "metadata_too_large", f"{label} has excessive metadata"
            )
        captured[name] = value
    after = os.lstat(path)
    if (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
    ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise TransactionError("file_changed", f"{label} changed while being read")
    return captured


def encode_xattrs(value: Mapping[str, bytes]) -> list[dict[str, str]]:
    return [
        {"name": name, "value": base64.b64encode(payload).decode("ascii")}
        for name, payload in sorted(value.items())
    ]


def decode_xattrs(value: Any) -> dict[str, bytes]:
    if not isinstance(value, list) or len(value) > MAX_XATTR_COUNT:
        raise TransactionError("invalid_state", "file metadata snapshot is invalid")
    result: dict[str, bytes] = {}
    total = 0
    for item in value:
        if not isinstance(item, dict) or set(item) != {"name", "value"}:
            raise TransactionError("invalid_state", "file metadata snapshot is invalid")
        name = item["name"]
        encoded = item["value"]
        if not isinstance(name, str) or not isinstance(encoded, str) or name in result:
            raise TransactionError("invalid_state", "file metadata snapshot is invalid")
        try:
            payload = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise TransactionError(
                "invalid_state", "file metadata snapshot is invalid"
            ) from exc
        total += len(name.encode()) + len(payload)
        if total > MAX_XATTR_BYTES:
            raise TransactionError("invalid_state", "file metadata snapshot is invalid")
        result[name] = payload
    return result


def apply_xattrs(path: Path, expected: Mapping[str, bytes]) -> None:
    if not all(
        callable(getattr(os, name, None))
        for name in ("listxattr", "setxattr", "removexattr")
    ):
        if expected or sys.platform.startswith("linux"):
            raise TransactionError(
                "metadata_unsupported", "extended attributes are required"
            )
        return
    try:
        existing = set(os.listxattr(path, follow_symlinks=False))
        for name in sorted(existing - set(expected)):
            os.removexattr(path, name, follow_symlinks=False)
        for name, payload in sorted(expected.items()):
            os.setxattr(path, name, payload, follow_symlinks=False)
    except OSError as exc:
        if not expected and exc.errno in {
            errno.ENOTSUP,
            getattr(errno, "EOPNOTSUPP", errno.ENOTSUP),
        }:
            return
        raise TransactionError(
            "metadata_restore_failed", "file metadata restore failed"
        ) from exc


def file_state(
    path: Path, *, label: str, max_bytes: int, owner_uid: int
) -> tuple[dict[str, Any], bytes, os.stat_result]:
    payload, info = read_regular_file(
        path, label=label, max_bytes=max_bytes, owner_uid=owner_uid
    )
    state = {
        "sha256": sha256_bytes(payload),
        "uid": info.st_uid,
        "gid": info.st_gid,
        "mode": stat.S_IMODE(info.st_mode),
        "size": len(payload),
        "xattrs": encode_xattrs(read_xattrs(path, info, label=label)),
    }
    return state, payload, info


def states_equal(first: Mapping[str, Any], second: Mapping[str, Any]) -> bool:
    return (
        hmac.compare_digest(str(first["sha256"]), str(second["sha256"]))
        and first["uid"] == second["uid"]
        and first["gid"] == second["gid"]
        and first["mode"] == second["mode"]
        and first["size"] == second["size"]
        and first["xattrs"] == second["xattrs"]
    )


def state_metadata(value: Any, *, max_bytes: int) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "sha256",
        "uid",
        "gid",
        "mode",
        "size",
        "xattrs",
    }:
        raise TransactionError("invalid_state", "file state snapshot is invalid")
    result = {
        "sha256": validate_sha256(value["sha256"], "file state"),
        "uid": validate_nonnegative_integer(value["uid"], "file owner"),
        "gid": validate_nonnegative_integer(value["gid"], "file group"),
        "mode": validate_nonnegative_integer(value["mode"], "file mode"),
        "size": validate_nonnegative_integer(value["size"], "file size"),
        "xattrs": encode_xattrs(decode_xattrs(value["xattrs"])),
    }
    if result["mode"] > 0o7777 or result["size"] > max_bytes:
        raise TransactionError("invalid_state", "file state snapshot is invalid")
    return result


def inspect_optional_target(
    path: Path, *, role: str, owner_uid: int
) -> tuple[dict[str, Any], bytes | None, os.stat_result | None]:
    assert_trusted_path(
        path.parent,
        label="proxy target parent",
        owner_uid=owner_uid,
        include_final=True,
    )
    if not stat.S_ISDIR(os.lstat(path.parent).st_mode):
        raise TransactionError("unsafe_path", "proxy target parent is not a directory")
    try:
        os.lstat(path)
    except FileNotFoundError:
        return {"existed": False}, None, None
    state, payload, info = file_state(
        path,
        label="existing proxy target",
        max_bytes=ROLE_LIMITS[role],
        owner_uid=owner_uid,
    )
    if info.st_uid != owner_uid or stat.S_IMODE(info.st_mode) & 0o022:
        raise TransactionError("unsafe_file", "existing proxy target is not protected")
    return {"existed": True, **state}, payload, info


def optional_target_matches(
    path: Path,
    expected: Mapping[str, Any],
    *,
    role: str,
    owner_uid: int,
) -> bool:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return expected.get("existed") is False
    if expected.get("existed") is False:
        return False
    actual, _payload, _info = file_state(
        path,
        label="proxy target",
        max_bytes=ROLE_LIMITS[role],
        owner_uid=owner_uid,
    )
    return states_equal(actual, expected)


def before_target_commit(_role: str, _operation: str) -> None:
    """Test seam immediately before a target rename/unlink."""


def before_source_recheck(_role: str) -> None:
    """Test seam immediately before a staged source is re-read."""


def before_provenance_check(_boundary: str) -> None:
    """Test seam immediately before a provenance boundary."""


def after_checkpoint(_phase: str, _intent: Mapping[str, Any] | None) -> None:
    """Test seam after a durable intent checkpoint."""


def atomic_install(
    path: Path,
    payload: bytes,
    desired: Mapping[str, Any],
    *,
    expected_current: Mapping[str, Any],
    role: str,
    owner_uid: int,
) -> None:
    assert_trusted_path(
        path.parent,
        label="proxy target parent",
        owner_uid=owner_uid,
        include_final=True,
    )
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent
        )
    except OSError as exc:
        raise TransactionError("install_failed", "proxy target staging failed") from exc
    temporary = Path(temporary_name)
    installed = False
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise TransactionError(
                "unsafe_file", "proxy target temporary file is unsafe"
            )
        os.fchown(descriptor, int(desired["uid"]), int(desired["gid"]))
        os.fchmod(descriptor, int(desired["mode"]))
        _write_all(descriptor, payload)
        apply_xattrs(temporary, decode_xattrs(desired["xattrs"]))
        applied = os.fstat(descriptor)
        if (
            applied.st_uid != desired["uid"]
            or applied.st_gid != desired["gid"]
            or stat.S_IMODE(applied.st_mode) != desired["mode"]
        ):
            raise TransactionError(
                "metadata_restore_failed", "proxy target metadata is wrong"
            )
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        before_target_commit(role, "install")
        if not optional_target_matches(
            path, expected_current, role=role, owner_uid=owner_uid
        ):
            raise TransactionError(
                "target_changed", "proxy target changed before install"
            )
        os.replace(temporary, path)
        installed = True
        fsync_directory(path.parent)
    except TransactionError:
        raise
    except OSError as exc:
        raise TransactionError("install_failed", "proxy target install failed") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if not installed:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def atomic_remove(
    path: Path,
    *,
    expected_current: Mapping[str, Any],
    role: str,
    owner_uid: int,
) -> None:
    before_target_commit(role, "remove")
    if not optional_target_matches(
        path, expected_current, role=role, owner_uid=owner_uid
    ):
        raise TransactionError("target_changed", "proxy target changed before removal")
    if expected_current.get("existed") is False:
        return
    try:
        os.unlink(path)
        fsync_directory(path.parent)
    except OSError as exc:
        raise TransactionError("remove_failed", "proxy target removal failed") from exc


def _parse_tinyproxy_config(payload: bytes) -> dict[str, list[str]]:
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise TransactionError("invalid_source", "proxy config is not UTF-8") from exc
    directives: dict[str, list[str]] = {}
    try:
        for raw_line in text.splitlines():
            words = shlex.split(raw_line, comments=True, posix=True)
            if not words:
                continue
            if words[0] in directives:
                raise TransactionError(
                    "invalid_source", "proxy config has duplicate directives"
                )
            directives[words[0]] = words[1:]
    except ValueError as exc:
        raise TransactionError(
            "invalid_source", "proxy config syntax is invalid"
        ) from exc
    expected = {
        "User": [PROXY_USER],
        "Group": [PROXY_GROUP],
        "Port": [str(LISTEN_PORT)],
        "Listen": [LISTEN_HOST],
        "Timeout": ["30"],
        "MaxClients": ["32"],
        "PidFile": ["/run/tinyproxy-galileo/tinyproxy.pid"],
        "Syslog": ["On"],
        "LogLevel": ["Info"],
        "Allow": [LISTEN_HOST],
        "ConnectPort": ["443"],
        "Filter": [str(TARGETS["proxy_filter"])],
        "FilterType": ["ere"],
        "FilterURLs": ["No"],
        "FilterCaseSensitive": ["Yes"],
        "FilterDefaultDeny": ["Yes"],
        "DisableViaHeader": ["Yes"],
    }
    if directives != expected:
        raise TransactionError(
            "invalid_source", "proxy config violates the exact policy"
        )
    return directives


def validate_filter(payload: bytes, allowed_host: str) -> None:
    expected = "^" + re.escape(allowed_host).replace(r"\-", "-") + "$\n"
    try:
        decoded = payload.decode("ascii", errors="strict")
    except UnicodeDecodeError as exc:
        raise TransactionError("invalid_source", "proxy filter is not ASCII") from exc
    if decoded != expected:
        raise TransactionError(
            "invalid_source", "proxy filter is not the exact host rule"
        )


def validate_unit(payload: bytes) -> None:
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise TransactionError("invalid_source", "proxy unit is not UTF-8") from exc
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    try:
        parser.read_string(text)
    except configparser.Error as exc:
        raise TransactionError(
            "invalid_source", "proxy unit syntax is invalid"
        ) from exc
    observed = {section: dict(parser[section]) for section in parser.sections()}
    if observed != UNIT_EXPECTED:
        raise TransactionError("invalid_source", "proxy unit violates the exact policy")


def validate_source_contents(
    sources: Mapping[str, Mapping[str, Any]], allowed_host: str
) -> None:
    validate_filter(sources["proxy_filter"]["payload"], allowed_host)
    _parse_tinyproxy_config(sources["proxy_config"]["payload"])
    validate_unit(sources["proxy_unit"]["payload"])


def parse_request(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict) or set(document) != {
        "schema_version",
        "state_root",
        "provenance",
        "proxy",
        "files",
    }:
        raise TransactionError("invalid_manifest", "proxy bundle request is invalid")
    if document.get("schema_version") != REQUEST_SCHEMA:
        raise TransactionError("invalid_manifest", "proxy bundle schema is invalid")
    state_root = absolute_path(document["state_root"], "state root")

    raw_provenance = document["provenance"]
    if not isinstance(raw_provenance, dict) or set(raw_provenance) != {
        "package_name",
        "package_version",
        "binary_package_name",
        "binary_package_version",
        "binary_path",
        "binary_sha256",
        "user",
        "group",
    }:
        raise TransactionError(
            "invalid_manifest", "proxy provenance request is invalid"
        )
    if raw_provenance["package_name"] != TINYPROXY_PACKAGE:
        raise TransactionError("invalid_manifest", "proxy package is not allowlisted")
    if raw_provenance["binary_package_name"] not in BINARY_PACKAGES:
        raise TransactionError(
            "invalid_manifest", "proxy binary package is not allowlisted"
        )
    for key in ("package_version", "binary_package_version"):
        if not isinstance(raw_provenance[key], str) or not SAFE_VERSION_RE.fullmatch(
            raw_provenance[key]
        ):
            raise TransactionError(
                "invalid_manifest", "proxy package version is invalid"
            )
    binary_path = absolute_path(raw_provenance["binary_path"], "proxy binary")
    if binary_path != TINYPROXY_BINARY:
        raise TransactionError(
            "invalid_manifest", "proxy binary path is not allowlisted"
        )
    if raw_provenance["user"] != PROXY_USER or raw_provenance["group"] != PROXY_GROUP:
        raise TransactionError("invalid_manifest", "proxy identity is not allowlisted")
    provenance = {
        **raw_provenance,
        "binary_path": str(binary_path),
        "binary_sha256": validate_sha256(
            raw_provenance["binary_sha256"], "proxy binary"
        ),
    }

    raw_proxy = document["proxy"]
    if not isinstance(raw_proxy, dict) or set(raw_proxy) != {
        "listen_host",
        "listen_port",
        "allowed_connect_host",
        "denied_connect_host",
        "probe_timeout_seconds",
    }:
        raise TransactionError("invalid_manifest", "proxy probe request is invalid")
    if (
        raw_proxy["listen_host"] != LISTEN_HOST
        or raw_proxy["listen_port"] != LISTEN_PORT
        or raw_proxy["denied_connect_host"] != DENIED_CONNECT_HOST
    ):
        raise TransactionError(
            "invalid_manifest", "proxy listener policy is not allowlisted"
        )
    proxy = {
        "listen_host": LISTEN_HOST,
        "listen_port": LISTEN_PORT,
        "allowed_connect_host": validate_dns_host(raw_proxy["allowed_connect_host"]),
        "denied_connect_host": DENIED_CONNECT_HOST,
        "probe_timeout_seconds": validate_timeout(raw_proxy["probe_timeout_seconds"]),
    }

    raw_files = document["files"]
    if not isinstance(raw_files, list) or len(raw_files) != len(ROLES):
        raise TransactionError(
            "invalid_manifest", "proxy request must contain three files"
        )
    files: dict[str, dict[str, Any]] = {}
    for raw in raw_files:
        if not isinstance(raw, dict) or set(raw) != {
            "role",
            "source",
            "target",
            "sha256",
            "uid",
            "gid",
            "mode",
        }:
            raise TransactionError("invalid_manifest", "proxy file entry is invalid")
        role = raw["role"]
        if role not in ROLES or role in files:
            raise TransactionError("invalid_manifest", "proxy file role is invalid")
        source = absolute_path(raw["source"], "staged proxy source")
        target = absolute_path(raw["target"], "proxy target")
        if target != TARGETS[role]:
            raise TransactionError("invalid_path", "proxy target is not allowlisted")
        files[role] = {
            "role": role,
            "source": str(source),
            "target": str(target),
            "sha256": validate_sha256(raw["sha256"], "staged proxy source"),
            "uid": validate_nonnegative_integer(raw["uid"], "staged owner"),
            "gid": validate_nonnegative_integer(raw["gid"], "staged group"),
            "mode": validate_mode(raw["mode"]),
        }
    if set(files) != set(ROLES):
        raise TransactionError(
            "invalid_manifest", "proxy request must declare every role"
        )
    sources = [entry["source"] for entry in files.values()]
    targets = [entry["target"] for entry in files.values()]
    if len(set(sources)) != len(sources) or len(set(targets)) != len(targets):
        raise TransactionError(
            "invalid_manifest", "proxy bundle paths must be distinct"
        )
    if set(sources) & set(targets):
        raise TransactionError(
            "invalid_manifest", "proxy source and target paths overlap"
        )
    for raw_path in (*sources, *targets):
        path = Path(raw_path)
        if (
            state_root == path
            or state_root in path.parents
            or path in state_root.parents
        ):
            raise TransactionError(
                "invalid_manifest", "state root overlaps proxy paths"
            )
    return {
        "schema_version": REQUEST_SCHEMA,
        "state_root": str(state_root),
        "provenance": provenance,
        "proxy": proxy,
        "files": files,
    }


def validate_requested_metadata(
    request: Mapping[str, Any], *, owner_uid: int, owner_gid: int
) -> None:
    for role in ROLES:
        entry = request["files"][role]
        if (entry["uid"], entry["gid"], entry["mode"]) != (
            owner_uid,
            owner_gid,
            ROLE_MODES[role],
        ):
            raise TransactionError(
                "invalid_metadata", "proxy source ownership or mode is not allowlisted"
            )


def capture_sources(
    request: Mapping[str, Any], *, owner_uid: int
) -> dict[str, dict[str, Any]]:
    captured: dict[str, dict[str, Any]] = {}
    for role in APPLY_ORDER:
        entry = request["files"][role]
        path = Path(entry["source"])
        state, payload, info = file_state(
            path,
            label="staged proxy source",
            max_bytes=ROLE_LIMITS[role],
            owner_uid=owner_uid,
        )
        if not payload:
            raise TransactionError("invalid_source", "staged proxy source is empty")
        if (
            not hmac.compare_digest(state["sha256"], entry["sha256"])
            or state["uid"] != entry["uid"]
            or state["gid"] != entry["gid"]
            or state["mode"] != entry["mode"]
            or state["xattrs"]
        ):
            raise TransactionError(
                "source_mismatch", "staged proxy source does not match"
            )
        captured[role] = {
            "path": path,
            "state": state,
            "payload": payload,
            "device": info.st_dev,
            "inode": info.st_ino,
            "mtime_ns": info.st_mtime_ns,
        }
    validate_source_contents(captured, request["proxy"]["allowed_connect_host"])
    return captured


def recheck_source(role: str, captured: Mapping[str, Any], *, owner_uid: int) -> bytes:
    before_source_recheck(role)
    state, payload, info = file_state(
        captured["path"],
        label="staged proxy source",
        max_bytes=ROLE_LIMITS[role],
        owner_uid=owner_uid,
    )
    if (
        not states_equal(state, captured["state"])
        or info.st_dev != captured["device"]
        or info.st_ino != captured["inode"]
        or info.st_mtime_ns != captured["mtime_ns"]
    ):
        raise TransactionError(
            "source_changed", "staged proxy source changed during apply"
        )
    return payload


def capture_targets(
    request: Mapping[str, Any], *, owner_uid: int
) -> dict[str, dict[str, Any]]:
    captured: dict[str, dict[str, Any]] = {}
    for role in APPLY_ORDER:
        path = Path(request["files"][role]["target"])
        state, payload, info = inspect_optional_target(
            path, role=role, owner_uid=owner_uid
        )
        captured[role] = {
            "state": state,
            "payload": payload,
            "device": info.st_dev if info is not None else None,
            "inode": info.st_ino if info is not None else None,
            "mtime_ns": info.st_mtime_ns if info is not None else None,
        }
    return captured


def verify_original_target(
    role: str, path: Path, captured: Mapping[str, Any], *, owner_uid: int
) -> None:
    if not optional_target_matches(
        path, captured["state"], role=role, owner_uid=owner_uid
    ):
        raise TransactionError("target_changed", "proxy target changed during snapshot")
    if captured["state"].get("existed"):
        _state, _payload, info = file_state(
            path,
            label="proxy target",
            max_bytes=ROLE_LIMITS[role],
            owner_uid=owner_uid,
        )
        if (
            info.st_dev != captured["device"]
            or info.st_ino != captured["inode"]
            or info.st_mtime_ns != captured["mtime_ns"]
        ):
            raise TransactionError(
                "target_changed", "proxy target changed during snapshot"
            )


def run_command(
    arguments: Sequence[str], *, timeout: float = 30.0
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
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
            "command_failed", "required local command failed"
        ) from exc
    if (
        len(result.stdout.encode("utf-8")) > MAX_COMMAND_OUTPUT
        or len(result.stderr.encode("utf-8")) > MAX_COMMAND_OUTPUT
    ):
        raise TransactionError(
            "command_failed", "required local command output is invalid"
        )
    return result


def executable_path(candidates: Sequence[str], label: str) -> str:
    for candidate in candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    raise TransactionError("command_missing", f"{label} is unavailable")


def host_fingerprint(*, owner_uid: int) -> str:
    for candidate in MACHINE_ID_PATHS:
        try:
            payload, info = read_regular_file(
                candidate,
                label="machine identity",
                max_bytes=4096,
                owner_uid=owner_uid,
            )
        except TransactionError:
            continue
        stripped = payload.strip()
        if (
            info.st_uid != 0
            or stat.S_IMODE(info.st_mode) & 0o022
            or not stripped
            or len(stripped) > 256
        ):
            continue
        return sha256_bytes(b"galileo-proxy-host-v1\0" + stripped)
    raise TransactionError("host_identity_failed", "machine identity is unavailable")


def package_version(package: str) -> str:
    if package not in {TINYPROXY_PACKAGE, *BINARY_PACKAGES}:
        raise TransactionError("package_failed", "proxy package is not allowlisted")
    if not (os.path.isfile(DPKG_QUERY) and os.access(DPKG_QUERY, os.X_OK)):
        raise TransactionError(
            "package_failed", "proxy package inventory is unavailable"
        )
    result = run_command((DPKG_QUERY, "-W", "-f=${Version}", "--", package))
    version = result.stdout.strip()
    if result.returncode != 0 or not SAFE_VERSION_RE.fullmatch(version):
        raise TransactionError("package_failed", "proxy package version is unavailable")
    return version


def binary_package(path: Path) -> str:
    result = run_command((DPKG_QUERY, "-S", "--", str(path)))
    if result.returncode != 0:
        raise TransactionError(
            "package_failed", "proxy binary ownership is unavailable"
        )
    records = [line for line in result.stdout.splitlines() if line]
    if len(records) != 1 or ": " not in records[0]:
        raise TransactionError("package_failed", "proxy binary ownership is ambiguous")
    raw_package, owned_path = records[0].rsplit(": ", 1)
    package = raw_package.split(":", 1)[0]
    if package not in BINARY_PACKAGES or owned_path != str(path):
        raise TransactionError("package_failed", "proxy binary ownership is invalid")
    return package


def binary_provenance(path: Path, *, owner_uid: int) -> dict[str, Any]:
    assert_trusted_path(
        path, label="proxy binary", owner_uid=owner_uid, include_final=True
    )
    state, _payload, info = file_state(
        path,
        label="proxy binary",
        max_bytes=MAX_BINARY_BYTES,
        owner_uid=owner_uid,
    )
    if (
        info.st_uid != 0
        or stat.S_IMODE(info.st_mode) & 0o022
        or not stat.S_IMODE(info.st_mode) & 0o111
    ):
        raise TransactionError("provenance_failed", "proxy binary is not protected")
    return {
        "path": str(path),
        "sha256": state["sha256"],
        "uid": state["uid"],
        "gid": state["gid"],
        "mode": state["mode"],
        "size": state["size"],
        "device": info.st_dev,
        "inode": info.st_ino,
        "mtime_ns": info.st_mtime_ns,
    }


def resolve_identity(user_name: str, group_name: str) -> tuple[int, int]:
    try:
        user = pwd.getpwnam(user_name)
        group = grp.getgrnam(group_name)
    except KeyError as exc:
        raise TransactionError(
            "identity_failed", "proxy identity is unavailable"
        ) from exc
    if user.pw_uid == 0 or group.gr_gid == 0:
        raise TransactionError("identity_failed", "proxy identity must be unprivileged")
    return user.pw_uid, group.gr_gid


def validate_file_provenance(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "path",
        "sha256",
        "uid",
        "gid",
        "mode",
        "size",
        "device",
        "inode",
        "mtime_ns",
    }:
        raise TransactionError("invalid_state", "binary provenance is invalid")
    path = absolute_path(value["path"], "proxy binary")
    if path != TINYPROXY_BINARY:
        raise TransactionError("invalid_state", "binary provenance is invalid")
    return {
        "path": str(path),
        "sha256": validate_sha256(value["sha256"], "proxy binary"),
        "uid": validate_nonnegative_integer(value["uid"], "binary owner"),
        "gid": validate_nonnegative_integer(value["gid"], "binary group"),
        "mode": validate_nonnegative_integer(value["mode"], "binary mode"),
        "size": validate_nonnegative_integer(value["size"], "binary size"),
        "device": validate_nonnegative_integer(value["device"], "binary device"),
        "inode": validate_nonnegative_integer(value["inode"], "binary inode"),
        "mtime_ns": validate_nonnegative_integer(value["mtime_ns"], "binary timestamp"),
    }


def validate_static_provenance(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "host_fingerprint",
        "package",
        "binary_package",
        "binary",
        "identity",
    }:
        raise TransactionError("invalid_state", "proxy provenance is invalid")
    host = validate_sha256(value["host_fingerprint"], "host identity")
    package = value["package"]
    binary_package_value = value["binary_package"]
    identity = value["identity"]
    if (
        not isinstance(package, dict)
        or set(package) != {"name", "version"}
        or package.get("name") != TINYPROXY_PACKAGE
        or not isinstance(package.get("version"), str)
        or not SAFE_VERSION_RE.fullmatch(package["version"])
        or not isinstance(binary_package_value, dict)
        or set(binary_package_value) != {"name", "version"}
        or binary_package_value.get("name") not in BINARY_PACKAGES
        or not isinstance(binary_package_value.get("version"), str)
        or not SAFE_VERSION_RE.fullmatch(binary_package_value["version"])
        or not isinstance(identity, dict)
        or set(identity) != {"user", "group", "uid", "gid"}
        or identity.get("user") != PROXY_USER
        or identity.get("group") != PROXY_GROUP
    ):
        raise TransactionError("invalid_state", "proxy provenance is invalid")
    normalized_identity = {
        "user": PROXY_USER,
        "group": PROXY_GROUP,
        "uid": validate_nonnegative_integer(identity["uid"], "proxy UID"),
        "gid": validate_nonnegative_integer(identity["gid"], "proxy GID"),
    }
    if normalized_identity["uid"] == 0 or normalized_identity["gid"] == 0:
        raise TransactionError("invalid_state", "proxy provenance is invalid")
    binary = validate_file_provenance(value["binary"])
    if (
        binary["uid"] != 0
        or binary["mode"] > 0o7777
        or binary["mode"] & 0o022
        or not binary["mode"] & 0o111
        or binary["size"] > MAX_BINARY_BYTES
    ):
        raise TransactionError("invalid_state", "proxy provenance is invalid")
    return {
        "host_fingerprint": host,
        "package": {"name": package["name"], "version": package["version"]},
        "binary_package": {
            "name": binary_package_value["name"],
            "version": binary_package_value["version"],
        },
        "binary": binary,
        "identity": normalized_identity,
    }


def validate_unit_state(value: Any, *, dedicated: bool) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"enabled_state", "active_state"}:
        raise TransactionError("invalid_state", "systemd unit state is invalid")
    enabled_allowed = {"enabled", "disabled"}
    if dedicated:
        enabled_allowed.add("not-found")
    if value["enabled_state"] not in enabled_allowed or value["active_state"] not in {
        "active",
        "inactive",
    }:
        raise TransactionError("invalid_state", "systemd unit state is unsupported")
    if value["enabled_state"] == "not-found" and value["active_state"] != "inactive":
        raise TransactionError("invalid_state", "missing systemd unit cannot be active")
    return {
        "enabled_state": value["enabled_state"],
        "active_state": value["active_state"],
    }


class ProxySystem:
    """Pinned local package, systemd, listener, and CONNECT-probe facade."""

    def __init__(self, *, owner_uid: int) -> None:
        self.owner_uid = owner_uid
        self.systemctl = executable_path(SYSTEMCTL_PATHS, "systemctl")
        self.systemd_analyze = executable_path(SYSTEMD_ANALYZE_PATHS, "systemd-analyze")
        self.ss = executable_path(SS_PATHS, "ss")

    def capture_static(self, request: Mapping[str, Any]) -> dict[str, Any]:
        requested = request["provenance"]
        binary_path = Path(requested["binary_path"])
        owned_by = binary_package(binary_path)
        uid, gid = resolve_identity(requested["user"], requested["group"])
        result = {
            "host_fingerprint": host_fingerprint(owner_uid=self.owner_uid),
            "package": {
                "name": requested["package_name"],
                "version": package_version(requested["package_name"]),
            },
            "binary_package": {
                "name": owned_by,
                "version": package_version(owned_by),
            },
            "binary": binary_provenance(binary_path, owner_uid=self.owner_uid),
            "identity": {
                "user": requested["user"],
                "group": requested["group"],
                "uid": uid,
                "gid": gid,
            },
        }
        expected_pairs = {
            "package_name": result["package"]["name"],
            "package_version": result["package"]["version"],
            "binary_package_name": result["binary_package"]["name"],
            "binary_package_version": result["binary_package"]["version"],
            "binary_path": result["binary"]["path"],
            "binary_sha256": result["binary"]["sha256"],
            "user": result["identity"]["user"],
            "group": result["identity"]["group"],
        }
        if any(requested[key] != observed for key, observed in expected_pairs.items()):
            raise TransactionError(
                "provenance_mismatch", "proxy provenance does not match request"
            )
        return validate_static_provenance(result)

    def verify_static(self, expected: Mapping[str, Any]) -> None:
        request = {
            "provenance": {
                "package_name": expected["package"]["name"],
                "package_version": expected["package"]["version"],
                "binary_package_name": expected["binary_package"]["name"],
                "binary_package_version": expected["binary_package"]["version"],
                "binary_path": expected["binary"]["path"],
                "binary_sha256": expected["binary"]["sha256"],
                "user": expected["identity"]["user"],
                "group": expected["identity"]["group"],
            }
        }
        actual = self.capture_static(request)
        if actual != expected:
            raise TransactionError("provenance_drift", "proxy provenance changed")

    def _unit_state(self, unit: str, *, dedicated: bool) -> dict[str, str]:
        enabled = run_command((self.systemctl, "is-enabled", "--", unit))
        active = run_command((self.systemctl, "is-active", "--", unit))
        enabled_state = enabled.stdout.strip()
        active_state = active.stdout.strip()
        return validate_unit_state(
            {"enabled_state": enabled_state, "active_state": active_state},
            dedicated=dedicated,
        )

    def capture_units(self) -> dict[str, dict[str, str]]:
        units = {
            "generic": self._unit_state(GENERIC_UNIT, dedicated=False),
            "dedicated": self._unit_state(DEDICATED_UNIT, dedicated=True),
        }
        if all(state["active_state"] == "active" for state in units.values()):
            raise TransactionError("unit_state_failed", "both proxy units are active")
        return units

    def query_unit(self, role: str) -> dict[str, str]:
        if role == "generic":
            return self._unit_state(GENERIC_UNIT, dedicated=False)
        if role == "dedicated":
            return self._unit_state(DEDICATED_UNIT, dedicated=True)
        raise TransactionError("invalid_state", "proxy unit role is invalid")

    def _systemctl_action(self, action: str, unit: str) -> None:
        if action not in {"enable", "disable", "start", "stop", "restart"}:
            raise TransactionError("invalid_state", "systemd action is invalid")
        result = run_command((self.systemctl, action, "--", unit))
        if result.returncode != 0:
            raise TransactionError("service_action_failed", "proxy unit action failed")

    def enable(self, unit: str) -> None:
        self._systemctl_action("enable", unit)

    def disable(self, unit: str) -> None:
        self._systemctl_action("disable", unit)

    def start(self, unit: str) -> None:
        self._systemctl_action("start", unit)

    def restart(self, unit: str) -> None:
        self._systemctl_action("restart", unit)

    def stop(self, unit: str) -> None:
        self._systemctl_action("stop", unit)

    def daemon_reload(self) -> None:
        result = run_command((self.systemctl, "daemon-reload"))
        if result.returncode != 0:
            raise TransactionError("daemon_reload_failed", "systemd reload failed")

    def verify_unit(self, path: Path) -> None:
        result = run_command((self.systemd_analyze, "--no-pager", "verify", str(path)))
        if result.returncode != 0:
            raise TransactionError(
                "unit_verification_failed", "proxy unit verification failed"
            )

    @staticmethod
    def _local_endpoint(value: str) -> tuple[str, int] | None:
        if value.startswith("[") and "]:" in value:
            host, raw_port = value[1:].rsplit("]:", 1)
        elif ":" in value:
            host, raw_port = value.rsplit(":", 1)
        else:
            return None
        try:
            port = int(raw_port)
        except ValueError:
            return None
        return host, port

    def listener(self, host: str, port: int) -> dict[str, Any]:
        result = run_command((self.ss, "-H", "-ltn"))
        if result.returncode != 0:
            raise TransactionError("listener_check_failed", "listener inventory failed")
        listeners: list[tuple[str, int]] = []
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) < 4:
                continue
            endpoint = self._local_endpoint(fields[3])
            if endpoint is not None and endpoint[1] == port:
                listeners.append(endpoint)
        if listeners != [(host, port)]:
            raise TransactionError(
                "listener_check_failed", "proxy listener is not exact loopback"
            )
        return {"checked": True, "ok": True}

    @staticmethod
    def _connect_status(host: str, port: int, target: str, timeout: float) -> int:
        request = (
            f"CONNECT {target}:443 HTTP/1.1\r\n"
            f"Host: {target}:443\r\n"
            "Proxy-Connection: close\r\n\r\n"
        ).encode("ascii")
        try:
            with socket.create_connection((host, port), timeout=timeout) as peer:
                peer.settimeout(timeout)
                peer.sendall(request)
                response = b""
                while b"\r\n" not in response and len(response) <= 8192:
                    chunk = peer.recv(1024)
                    if not chunk:
                        break
                    response += chunk
        except OSError as exc:
            raise TransactionError(
                "probe_failed", "proxy CONNECT probe failed"
            ) from exc
        first_line = response.split(b"\r\n", 1)[0]
        match = HTTP_STATUS_RE.match(first_line)
        if not match:
            raise TransactionError("probe_failed", "proxy CONNECT response is invalid")
        return int(match.group(1))

    def probes(self, proxy: Mapping[str, Any]) -> dict[str, Any]:
        listener = self.listener(proxy["listen_host"], proxy["listen_port"])
        denied = self._connect_status(
            proxy["listen_host"],
            proxy["listen_port"],
            proxy["denied_connect_host"],
            proxy["probe_timeout_seconds"],
        )
        if denied != 403:
            raise TransactionError(
                "probe_failed", "proxy deny probe did not fail closed"
            )
        allowed = self._connect_status(
            proxy["listen_host"],
            proxy["listen_port"],
            proxy["allowed_connect_host"],
            proxy["probe_timeout_seconds"],
        )
        if not 200 <= allowed <= 299:
            raise TransactionError("probe_failed", "proxy allow probe did not succeed")
        return {
            "listener": listener,
            "denied_connect": {"checked": True, "ok": True, "status_code": 403},
            "allowed_connect": {"checked": True, "ok": True, "status_class": "2xx"},
        }


def verify_boundary(
    system: Any, provenance: Mapping[str, Any], *, boundary: str
) -> None:
    before_provenance_check(boundary)
    system.verify_static(provenance)


def current_units(system: Any) -> dict[str, dict[str, str]]:
    units = {
        "generic": validate_unit_state(system.query_unit("generic"), dedicated=False),
        "dedicated": validate_unit_state(
            system.query_unit("dedicated"), dedicated=True
        ),
    }
    if all(state["active_state"] == "active" for state in units.values()):
        raise TransactionError("unit_state_failed", "both proxy units are active")
    return units


def require_units(system: Any, expected: Mapping[str, Mapping[str, str]]) -> None:
    if current_units(system) != expected:
        raise TransactionError(
            "unit_state_drift", "proxy unit state changed during transaction"
        )


def acquire_lock(state_root: Path, *, owner_uid: int, owner_gid: int) -> BinaryIO:
    path = state_root / ".transaction.lock"
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise TransactionError("lock_failed", "proxy transaction lock failed") from exc
    handle = os.fdopen(descriptor, "r+b", buffering=0)
    try:
        info = os.fstat(descriptor)
        named = os.lstat(path)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_dev != named.st_dev
            or info.st_ino != named.st_ino
            or info.st_uid != owner_uid
        ):
            raise TransactionError("unsafe_lock", "proxy transaction lock is unsafe")
        os.fchown(descriptor, owner_uid, owner_gid)
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise TransactionError(
                "transaction_busy", "another proxy transaction is active"
            ) from exc
        return handle
    except BaseException:
        handle.close()
        raise


def create_state_directory(
    state_root: Path, generation: str, *, owner_uid: int
) -> Path:
    directory = state_root / f"generation-{generation}"
    try:
        os.mkdir(directory, 0o700)
        os.chmod(directory, 0o700, follow_symlinks=False)
        fsync_directory(state_root)
    except OSError as exc:
        raise TransactionError(
            "state_write_failed", "transaction generation creation failed"
        ) from exc
    assert_private_directory(
        directory, owner_uid=owner_uid, label="transaction generation"
    )
    return directory


def current_path(state_root: Path) -> Path:
    return state_root / "current.json"


def load_current(
    state_root: Path, *, owner_uid: int, required: bool
) -> dict[str, Any] | None:
    path = current_path(state_root)
    try:
        os.lstat(path)
    except FileNotFoundError:
        if required:
            raise TransactionError(
                "current_missing", "current proxy transaction is missing"
            )
        return None
    document, _payload, _info = read_private_json(
        path,
        label="current proxy transaction",
        max_bytes=MAX_STATE_BYTES,
        owner_uid=owner_uid,
    )
    if (
        set(document) != {"schema_version", "generation", "manifest_sha256"}
        or document.get("schema_version") != CURRENT_SCHEMA
        or not isinstance(document.get("generation"), str)
        or not GENERATION_RE.fullmatch(document["generation"])
    ):
        raise TransactionError("invalid_state", "current proxy transaction is invalid")
    validate_sha256(document.get("manifest_sha256"), "current manifest")
    return document


def install_current(
    state_root: Path,
    generation: str,
    manifest_payload: bytes,
    *,
    owner_uid: int,
    owner_gid: int,
) -> None:
    write_atomic_private(
        current_path(state_root),
        json_bytes(
            {
                "schema_version": CURRENT_SCHEMA,
                "generation": generation,
                "manifest_sha256": sha256_bytes(manifest_payload),
            }
        ),
        owner_uid=owner_uid,
        owner_gid=owner_gid,
    )


def release_current(state_root: Path, generation: str, *, owner_uid: int) -> None:
    current = load_current(state_root, owner_uid=owner_uid, required=False)
    if current is None:
        return
    if current["generation"] != generation:
        raise TransactionError("stale_transaction", "proxy transaction is not current")
    try:
        os.unlink(current_path(state_root))
        fsync_directory(state_root)
    except OSError as exc:
        raise TransactionError(
            "state_write_failed", "current transaction release failed"
        ) from exc


def validate_proxy_state(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "listen_host",
        "listen_port",
        "allowed_connect_host",
        "denied_connect_host",
        "probe_timeout_seconds",
    }:
        raise TransactionError("invalid_state", "proxy probe state is invalid")
    if (
        value["listen_host"] != LISTEN_HOST
        or value["listen_port"] != LISTEN_PORT
        or value["denied_connect_host"] != DENIED_CONNECT_HOST
    ):
        raise TransactionError("invalid_state", "proxy probe state is invalid")
    return {
        "listen_host": LISTEN_HOST,
        "listen_port": LISTEN_PORT,
        "allowed_connect_host": validate_dns_host(value["allowed_connect_host"]),
        "denied_connect_host": DENIED_CONNECT_HOST,
        "probe_timeout_seconds": validate_timeout(value["probe_timeout_seconds"]),
    }


def validate_original_file(value: Any, *, role: str) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or "existed" not in value
        or not isinstance(value["existed"], bool)
    ):
        raise TransactionError("invalid_state", "original proxy file state is invalid")
    if not value["existed"]:
        if set(value) != {"existed"}:
            raise TransactionError(
                "invalid_state", "absent proxy file state is invalid"
            )
        return {"existed": False}
    if set(value) != {
        "existed",
        "sha256",
        "uid",
        "gid",
        "mode",
        "size",
        "xattrs",
        "backup",
    }:
        raise TransactionError("invalid_state", "original proxy file state is invalid")
    backup = value["backup"]
    if not isinstance(backup, str) or not re.fullmatch(r"backup-[0-2]\.bin", backup):
        raise TransactionError("invalid_state", "proxy backup reference is invalid")
    return {
        "existed": True,
        **state_metadata(
            {
                key: value[key]
                for key in ("sha256", "uid", "gid", "mode", "size", "xattrs")
            },
            max_bytes=ROLE_LIMITS[role],
        ),
        "backup": backup,
    }


def validate_state_document(
    value: Any, manifest_path: Path, *, owner_uid: int, owner_gid: int
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "generation",
        "created_at",
        "state_root",
        "owner_uid",
        "owner_gid",
        "request_sha256",
        "provenance",
        "proxy",
        "units",
        "files",
    }:
        raise TransactionError("invalid_state", "proxy transaction manifest is invalid")
    if value.get("schema_version") != STATE_SCHEMA:
        raise TransactionError("invalid_state", "proxy transaction manifest is invalid")
    generation = value.get("generation")
    if not isinstance(generation, str) or not GENERATION_RE.fullmatch(generation):
        raise TransactionError("invalid_state", "proxy generation is invalid")
    state_root = absolute_path(value.get("state_root"), "transaction state root")
    expected_path = state_root / f"generation-{generation}" / "manifest.json"
    if manifest_path != expected_path:
        raise TransactionError("invalid_state", "proxy manifest location is invalid")
    if value.get("owner_uid") != owner_uid:
        raise TransactionError("invalid_state", "proxy transaction owner is invalid")
    if value.get("owner_gid") != owner_gid:
        raise TransactionError("invalid_state", "proxy transaction group is invalid")
    created_at = value.get("created_at")
    if (
        not isinstance(created_at, str)
        or len(created_at) != 20
        or not created_at.endswith("Z")
    ):
        raise TransactionError(
            "invalid_state", "proxy transaction timestamp is invalid"
        )
    request_sha = validate_sha256(value.get("request_sha256"), "proxy request")
    provenance = validate_static_provenance(value.get("provenance"))
    proxy = validate_proxy_state(value.get("proxy"))
    units_value = value.get("units")
    if not isinstance(units_value, dict) or set(units_value) != {
        "generic",
        "dedicated",
    }:
        raise TransactionError("invalid_state", "proxy unit snapshot is invalid")
    units = {
        "generic": validate_unit_state(units_value["generic"], dedicated=False),
        "dedicated": validate_unit_state(units_value["dedicated"], dedicated=True),
    }
    if all(state["active_state"] == "active" for state in units.values()):
        raise TransactionError("invalid_state", "proxy unit snapshot is invalid")
    files_value = value.get("files")
    if not isinstance(files_value, list) or len(files_value) != len(ROLES):
        raise TransactionError("invalid_state", "proxy file inventory is invalid")
    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, entry in enumerate(files_value):
        if not isinstance(entry, dict) or set(entry) != {
            "role",
            "target",
            "desired",
            "original",
        }:
            raise TransactionError("invalid_state", "proxy file entry is invalid")
        role = entry["role"]
        if role not in ROLES or role in seen or role != APPLY_ORDER[index]:
            raise TransactionError("invalid_state", "proxy file order is invalid")
        seen.add(role)
        target = absolute_path(entry["target"], "proxy target")
        if target != TARGETS[role]:
            raise TransactionError("invalid_state", "proxy target is not allowlisted")
        desired = state_metadata(entry["desired"], max_bytes=ROLE_LIMITS[role])
        if (
            desired["uid"] != owner_uid
            or desired["gid"] != owner_gid
            or desired["mode"] != ROLE_MODES[role]
            or desired["xattrs"]
        ):
            raise TransactionError("invalid_state", "proxy desired metadata is invalid")
        files.append(
            {
                "role": role,
                "target": str(target),
                "desired": desired,
                "original": validate_original_file(entry["original"], role=role),
            }
        )
    return {
        "schema_version": STATE_SCHEMA,
        "generation": generation,
        "created_at": created_at,
        "state_root": str(state_root),
        "owner_uid": owner_uid,
        "owner_gid": owner_gid,
        "request_sha256": request_sha,
        "provenance": provenance,
        "proxy": proxy,
        "units": units,
        "files": files,
    }


def load_state_manifest(
    path: Path, *, owner_uid: int, owner_gid: int
) -> tuple[dict[str, Any], bytes]:
    document, payload, _info = read_private_json(
        path,
        label="proxy transaction manifest",
        max_bytes=MAX_STATE_BYTES,
        owner_uid=owner_uid,
    )
    return validate_state_document(
        document, path, owner_uid=owner_uid, owner_gid=owner_gid
    ), payload


def require_current_ownership(
    document: Mapping[str, Any], manifest_payload: bytes, *, owner_uid: int
) -> None:
    current = load_current(
        Path(document["state_root"]), owner_uid=owner_uid, required=True
    )
    assert current is not None
    if current["generation"] != document["generation"] or not hmac.compare_digest(
        current["manifest_sha256"], sha256_bytes(manifest_payload)
    ):
        raise TransactionError("stale_transaction", "proxy transaction is not current")


def initial_journal(generation: str) -> dict[str, Any]:
    return {
        "schema_version": JOURNAL_SCHEMA,
        "generation": generation,
        "phase": "prepared",
        "sequence": 0,
        "intent": None,
        "updated_at": utc_now(),
    }


def validate_journal(value: Any, generation: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "generation",
        "phase",
        "sequence",
        "intent",
        "updated_at",
    }:
        raise TransactionError("invalid_state", "proxy transaction journal is invalid")
    if (
        value.get("schema_version") != JOURNAL_SCHEMA
        or value.get("generation") != generation
    ):
        raise TransactionError("invalid_state", "proxy transaction journal is invalid")
    phase = value.get("phase")
    if phase not in {
        "prepared",
        "applying",
        "applied",
        "restoring",
        "restored",
        "recovery_required",
    }:
        raise TransactionError("invalid_state", "proxy transaction phase is invalid")
    sequence = validate_nonnegative_integer(value.get("sequence"), "journal sequence")
    intent = value.get("intent")
    if intent is not None:
        if (
            not isinstance(intent, dict)
            or set(intent) != {"kind", "index"}
            or intent.get("kind")
            not in {"apply_file", "apply_action", "restore_action", "restore_file"}
            or isinstance(intent.get("index"), bool)
            or not isinstance(intent.get("index"), int)
            or not 0 <= intent["index"] <= 16
        ):
            raise TransactionError(
                "invalid_state", "proxy transaction intent is invalid"
            )
    updated = value.get("updated_at")
    if not isinstance(updated, str) or len(updated) != 20 or not updated.endswith("Z"):
        raise TransactionError("invalid_state", "proxy journal timestamp is invalid")
    return {
        "schema_version": JOURNAL_SCHEMA,
        "generation": generation,
        "phase": phase,
        "sequence": sequence,
        "intent": copy.deepcopy(intent),
        "updated_at": updated,
    }


def journal_path(document: Mapping[str, Any]) -> Path:
    return (
        Path(document["state_root"])
        / f"generation-{document['generation']}"
        / "journal.json"
    )


def load_journal(document: Mapping[str, Any], *, owner_uid: int) -> dict[str, Any]:
    raw, _payload, _info = read_private_json(
        journal_path(document),
        label="proxy transaction journal",
        max_bytes=MAX_STATE_BYTES,
        owner_uid=owner_uid,
    )
    return validate_journal(raw, str(document["generation"]))


def checkpoint(
    document: Mapping[str, Any],
    journal: Mapping[str, Any],
    *,
    phase: str,
    intent: Mapping[str, Any] | None,
    owner_uid: int,
    owner_gid: int,
) -> dict[str, Any]:
    candidate = {
        "schema_version": JOURNAL_SCHEMA,
        "generation": document["generation"],
        "phase": phase,
        "sequence": int(journal["sequence"]) + 1,
        "intent": copy.deepcopy(intent),
        "updated_at": utc_now(),
    }
    normalized = validate_journal(candidate, str(document["generation"]))
    write_atomic_private(
        journal_path(document),
        json_bytes(normalized),
        owner_uid=owner_uid,
        owner_gid=owner_gid,
    )
    after_checkpoint(phase, intent)
    return normalized


def mark_recovery_required(
    document: Mapping[str, Any], *, owner_uid: int, owner_gid: int
) -> None:
    try:
        journal = load_journal(document, owner_uid=owner_uid)
        checkpoint(
            document,
            journal,
            phase="recovery_required",
            intent=journal["intent"],
            owner_uid=owner_uid,
            owner_gid=owner_gid,
        )
    except BaseException:
        pass


def prepare_state(
    request: Mapping[str, Any],
    request_sha256: str,
    provenance: Mapping[str, Any],
    units: Mapping[str, Mapping[str, str]],
    sources: Mapping[str, Mapping[str, Any]],
    targets: Mapping[str, Mapping[str, Any]],
    state_dir: Path,
    generation: str,
    *,
    owner_uid: int,
    owner_gid: int,
) -> tuple[dict[str, Any], bytes]:
    files: list[dict[str, Any]] = []
    for index, role in enumerate(APPLY_ORDER):
        original_state = targets[role]["state"]
        if original_state["existed"]:
            backup_name = f"backup-{index}.bin"
            backup_payload = targets[role]["payload"]
            assert isinstance(backup_payload, bytes)
            write_exclusive(
                state_dir / backup_name,
                backup_payload,
                mode=0o600,
                owner_uid=owner_uid,
                owner_gid=owner_gid,
            )
            original = {**original_state, "backup": backup_name}
        else:
            original = {"existed": False}
        files.append(
            {
                "role": role,
                "target": request["files"][role]["target"],
                "desired": sources[role]["state"],
                "original": original,
            }
        )
    document = {
        "schema_version": STATE_SCHEMA,
        "generation": generation,
        "created_at": utc_now(),
        "state_root": request["state_root"],
        "owner_uid": owner_uid,
        "owner_gid": owner_gid,
        "request_sha256": request_sha256,
        "provenance": copy.deepcopy(provenance),
        "proxy": copy.deepcopy(request["proxy"]),
        "units": copy.deepcopy(units),
        "files": files,
    }
    manifest_path = state_dir / "manifest.json"
    normalized = validate_state_document(
        document,
        manifest_path,
        owner_uid=owner_uid,
        owner_gid=owner_gid,
    )
    payload = json_bytes(normalized)
    write_exclusive(
        manifest_path,
        payload,
        mode=0o600,
        owner_uid=owner_uid,
        owner_gid=owner_gid,
    )
    write_exclusive(
        state_dir / "journal.json",
        json_bytes(initial_journal(generation)),
        mode=0o600,
        owner_uid=owner_uid,
        owner_gid=owner_gid,
    )
    install_current(
        Path(request["state_root"]),
        generation,
        payload,
        owner_uid=owner_uid,
        owner_gid=owner_gid,
    )
    return normalized, payload


def cleanup_uncommitted_state(state_dir: Path, *, state_root: Path) -> None:
    """Remove only a just-created generation that never obtained current ownership."""

    try:
        for path in state_dir.iterdir():
            info = os.lstat(path)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                return
        for path in state_dir.iterdir():
            os.unlink(path)
        os.rmdir(state_dir)
        fsync_directory(state_root)
    except (FileNotFoundError, OSError, TransactionError):
        return


def apply_files(
    document: Mapping[str, Any],
    sources: Mapping[str, Mapping[str, Any]],
    targets: Mapping[str, Mapping[str, Any]],
    system: Any,
    *,
    owner_uid: int,
    owner_gid: int,
) -> dict[str, Any]:
    journal = load_journal(document, owner_uid=owner_uid)
    by_role = {entry["role"]: entry for entry in document["files"]}
    expected_units = copy.deepcopy(document["units"])
    for index, role in enumerate(APPLY_ORDER):
        journal = checkpoint(
            document,
            journal,
            phase="applying",
            intent={"kind": "apply_file", "index": index},
            owner_uid=owner_uid,
            owner_gid=owner_gid,
        )
        verify_boundary(
            system, document["provenance"], boundary=f"before-apply-file-{index}"
        )
        require_units(system, expected_units)
        entry = by_role[role]
        target = Path(entry["target"])
        verify_original_target(role, target, targets[role], owner_uid=owner_uid)
        payload = recheck_source(role, sources[role], owner_uid=owner_uid)
        atomic_install(
            target,
            payload,
            entry["desired"],
            expected_current=targets[role]["state"],
            role=role,
            owner_uid=owner_uid,
        )
        if not optional_target_matches(
            target,
            {"existed": True, **entry["desired"]},
            role=role,
            owner_uid=owner_uid,
        ):
            raise TransactionError(
                "install_verification_failed", "proxy install verification failed"
            )
        # `systemctl is-enabled` can discover a newly installed unit file
        # before daemon-reload. Treat that exact not-found -> disabled,
        # inactive transition as part of committing the proxy_unit role.
        if (
            role == "proxy_unit"
            and expected_units["dedicated"]["enabled_state"] == "not-found"
        ):
            expected_units["dedicated"] = {
                "enabled_state": "disabled",
                "active_state": "inactive",
            }
        verify_boundary(
            system, document["provenance"], boundary=f"after-apply-file-{index}"
        )
        require_units(system, expected_units)
        journal = checkpoint(
            document,
            journal,
            phase="applying",
            intent=None,
            owner_uid=owner_uid,
            owner_gid=owner_gid,
        )
    return journal


APPLY_ACTIONS = (
    "daemon_reload",
    "verify_unit",
    "disable_generic",
    "stop_generic",
    "enable_dedicated",
    "restart_dedicated",
    "verify_units",
    "probes",
)


def verify_desired_units(system: Any) -> None:
    generic = system.query_unit("generic")
    dedicated = system.query_unit("dedicated")
    if generic != {"enabled_state": "disabled", "active_state": "inactive"}:
        raise TransactionError(
            "unit_state_failed", "generic proxy unit is not disabled and stopped"
        )
    if dedicated != {"enabled_state": "enabled", "active_state": "active"}:
        raise TransactionError(
            "unit_state_failed", "dedicated proxy unit is not enabled and active"
        )


def run_apply_actions(
    document: Mapping[str, Any],
    journal: dict[str, Any],
    system: Any,
    *,
    owner_uid: int,
    owner_gid: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    probes: dict[str, Any] = {
        "listener": {"checked": False, "ok": False},
        "denied_connect": {"checked": False, "ok": False},
        "allowed_connect": {"checked": False, "ok": False},
    }
    expected_units = copy.deepcopy(document["units"])
    if expected_units["dedicated"]["enabled_state"] == "not-found":
        expected_units["dedicated"] = {
            "enabled_state": "disabled",
            "active_state": "inactive",
        }
    for index, action in enumerate(APPLY_ACTIONS):
        journal = checkpoint(
            document,
            journal,
            phase="applying",
            intent={"kind": "apply_action", "index": index},
            owner_uid=owner_uid,
            owner_gid=owner_gid,
        )
        verify_boundary(
            system, document["provenance"], boundary=f"before-apply-action-{index}"
        )
        require_units(system, expected_units)
        if action == "daemon_reload":
            system.daemon_reload()
        elif action == "verify_unit":
            system.verify_unit(TARGETS["proxy_unit"])
        elif action == "disable_generic":
            system.disable(GENERIC_UNIT)
            expected_units["generic"]["enabled_state"] = "disabled"
        elif action == "stop_generic":
            system.stop(GENERIC_UNIT)
            expected_units["generic"]["active_state"] = "inactive"
        elif action == "enable_dedicated":
            system.enable(DEDICATED_UNIT)
            expected_units["dedicated"]["enabled_state"] = "enabled"
        elif action == "restart_dedicated":
            # `start` is a no-op when a prior dedicated generation is already
            # active.  Restart guarantees that the process serving the live
            # probes loaded this transaction's exact config and unit.
            system.restart(DEDICATED_UNIT)
            expected_units["dedicated"]["active_state"] = "active"
        elif action == "verify_units":
            verify_desired_units(system)
        else:
            probes = system.probes(document["proxy"])
        verify_boundary(
            system, document["provenance"], boundary=f"after-apply-action-{index}"
        )
        require_units(system, expected_units)
        journal = checkpoint(
            document,
            journal,
            phase="applying",
            intent=None,
            owner_uid=owner_uid,
            owner_gid=owner_gid,
        )
    return journal, probes


def load_backup(
    document: Mapping[str, Any], entry: Mapping[str, Any], *, owner_uid: int
) -> bytes:
    original = entry["original"]
    if not original["existed"]:
        raise TransactionError("invalid_state", "absent proxy file has no backup")
    state_dir = Path(document["state_root"]) / f"generation-{document['generation']}"
    backup_path = state_dir / original["backup"]
    payload, info = read_regular_file(
        backup_path,
        label="proxy transaction backup",
        max_bytes=ROLE_LIMITS[entry["role"]],
        owner_uid=owner_uid,
    )
    if info.st_uid != owner_uid or stat.S_IMODE(info.st_mode) != 0o600:
        raise TransactionError("unsafe_backup", "proxy backup is not protected")
    if len(payload) != original["size"] or not hmac.compare_digest(
        sha256_bytes(payload), original["sha256"]
    ):
        raise TransactionError(
            "backup_hash_mismatch", "proxy backup does not match snapshot"
        )
    return payload


def restore_one_file(
    document: Mapping[str, Any], entry: Mapping[str, Any], *, owner_uid: int
) -> None:
    role = entry["role"]
    target = Path(entry["target"])
    original = entry["original"]
    desired = {"existed": True, **entry["desired"]}
    is_original = optional_target_matches(
        target, original, role=role, owner_uid=owner_uid
    )
    is_desired = optional_target_matches(
        target, desired, role=role, owner_uid=owner_uid
    )
    if not is_original and not is_desired:
        raise TransactionError(
            "target_drift", "proxy target matches neither transaction state"
        )
    if not is_original:
        if original["existed"]:
            atomic_install(
                target,
                load_backup(document, entry, owner_uid=owner_uid),
                original,
                expected_current=desired,
                role=role,
                owner_uid=owner_uid,
            )
        else:
            atomic_remove(
                target,
                expected_current=desired,
                role=role,
                owner_uid=owner_uid,
            )
    if not optional_target_matches(target, original, role=role, owner_uid=owner_uid):
        raise TransactionError(
            "restore_verification_failed", "proxy file restore is incomplete"
        )


def quiesce_unit(system: Any, role: str, unit: str) -> None:
    state = system.query_unit(role)
    if state["active_state"] == "active":
        system.stop(unit)
        state = system.query_unit(role)
    if state["enabled_state"] == "enabled":
        system.disable(unit)


def restore_enablement(
    system: Any, role: str, unit: str, expected: Mapping[str, str]
) -> None:
    observed = system.query_unit(role)
    target = expected["enabled_state"]
    if target == "enabled":
        if observed["enabled_state"] != "enabled":
            system.enable(unit)
    elif target == "disabled":
        if observed["enabled_state"] != "disabled":
            system.disable(unit)
    elif observed["enabled_state"] != "not-found":
        raise TransactionError(
            "unit_restore_failed", "missing proxy unit was not restored"
        )


def restore_active(
    system: Any, role: str, unit: str, expected: Mapping[str, str]
) -> None:
    observed = system.query_unit(role)
    target = expected["active_state"]
    if target == "active" and observed["active_state"] != "active":
        system.start(unit)
    elif target == "inactive" and observed["active_state"] == "active":
        system.stop(unit)


def verify_original_units(
    system: Any, expected: Mapping[str, Mapping[str, str]]
) -> None:
    if system.query_unit("generic") != expected["generic"]:
        raise TransactionError(
            "unit_restore_failed", "generic proxy unit state was not restored"
        )
    if system.query_unit("dedicated") != expected["dedicated"]:
        raise TransactionError(
            "unit_restore_failed", "dedicated proxy unit state was not restored"
        )


def restore_from_document(
    document: Mapping[str, Any],
    manifest_payload: bytes,
    system: Any,
    *,
    owner_uid: int,
    owner_gid: int,
) -> dict[str, Any]:
    journal = load_journal(document, owner_uid=owner_uid)
    current = load_current(
        Path(document["state_root"]), owner_uid=owner_uid, required=False
    )
    if journal["phase"] == "restored" and current is None:
        verify_boundary(
            system, document["provenance"], boundary="verify-completed-restore"
        )
        for entry in document["files"]:
            if not optional_target_matches(
                Path(entry["target"]),
                entry["original"],
                role=entry["role"],
                owner_uid=owner_uid,
            ):
                raise TransactionError(
                    "restore_verification_failed", "completed proxy restore has drifted"
                )
        verify_original_units(system, document["units"])
        return {"status": "restored", "unit_state_restored": True}
    require_current_ownership(document, manifest_payload, owner_uid=owner_uid)
    journal = checkpoint(
        document,
        journal,
        phase="restoring",
        intent=None,
        owner_uid=owner_uid,
        owner_gid=owner_gid,
    )

    restore_actions = (
        (
            "quiesce_dedicated",
            lambda: quiesce_unit(system, "dedicated", DEDICATED_UNIT),
        ),
        ("quiesce_generic", lambda: quiesce_unit(system, "generic", GENERIC_UNIT)),
    )
    for index, (_name, action) in enumerate(restore_actions):
        journal = checkpoint(
            document,
            journal,
            phase="restoring",
            intent={"kind": "restore_action", "index": index},
            owner_uid=owner_uid,
            owner_gid=owner_gid,
        )
        verify_boundary(
            system, document["provenance"], boundary=f"before-restore-action-{index}"
        )
        action()
        verify_boundary(
            system, document["provenance"], boundary=f"after-restore-action-{index}"
        )
        journal = checkpoint(
            document,
            journal,
            phase="restoring",
            intent=None,
            owner_uid=owner_uid,
            owner_gid=owner_gid,
        )

    by_role = {entry["role"]: entry for entry in document["files"]}
    for index, role in enumerate(RESTORE_ORDER):
        journal = checkpoint(
            document,
            journal,
            phase="restoring",
            intent={"kind": "restore_file", "index": index},
            owner_uid=owner_uid,
            owner_gid=owner_gid,
        )
        verify_boundary(
            system, document["provenance"], boundary=f"before-restore-file-{index}"
        )
        restore_one_file(document, by_role[role], owner_uid=owner_uid)
        verify_boundary(
            system, document["provenance"], boundary=f"after-restore-file-{index}"
        )
        journal = checkpoint(
            document,
            journal,
            phase="restoring",
            intent=None,
            owner_uid=owner_uid,
            owner_gid=owner_gid,
        )

    final_actions = (
        lambda: system.daemon_reload(),
        lambda: restore_enablement(
            system, "generic", GENERIC_UNIT, document["units"]["generic"]
        ),
        lambda: restore_enablement(
            system, "dedicated", DEDICATED_UNIT, document["units"]["dedicated"]
        ),
        lambda: restore_active(
            system, "generic", GENERIC_UNIT, document["units"]["generic"]
        ),
        lambda: restore_active(
            system, "dedicated", DEDICATED_UNIT, document["units"]["dedicated"]
        ),
        lambda: verify_original_units(system, document["units"]),
    )
    for offset, action in enumerate(final_actions, start=len(restore_actions)):
        journal = checkpoint(
            document,
            journal,
            phase="restoring",
            intent={"kind": "restore_action", "index": offset},
            owner_uid=owner_uid,
            owner_gid=owner_gid,
        )
        verify_boundary(
            system, document["provenance"], boundary=f"before-restore-action-{offset}"
        )
        action()
        verify_boundary(
            system, document["provenance"], boundary=f"after-restore-action-{offset}"
        )
        journal = checkpoint(
            document,
            journal,
            phase="restoring",
            intent=None,
            owner_uid=owner_uid,
            owner_gid=owner_gid,
        )

    for entry in document["files"]:
        if not optional_target_matches(
            Path(entry["target"]),
            entry["original"],
            role=entry["role"],
            owner_uid=owner_uid,
        ):
            raise TransactionError(
                "restore_verification_failed", "proxy restore is incomplete"
            )
    journal = checkpoint(
        document,
        journal,
        phase="restored",
        intent=None,
        owner_uid=owner_uid,
        owner_gid=owner_gid,
    )
    release_current(
        Path(document["state_root"]), str(document["generation"]), owner_uid=owner_uid
    )
    return {"status": "restored", "unit_state_restored": True}


def _as_transaction_error(error: BaseException) -> TransactionError:
    if isinstance(error, TransactionError):
        return error
    if isinstance(error, (KeyboardInterrupt, SystemExit)):
        return TransactionError("interrupted", "proxy transaction was interrupted")
    return TransactionError("apply_failed", "proxy transaction failed")


def apply_proxy_bundle(
    request_path: Path,
    *,
    system: Any | None = None,
    owner_uid: int | None = None,
    owner_gid: int | None = None,
) -> dict[str, Any]:
    uid = os.geteuid() if owner_uid is None else owner_uid
    gid = os.getegid() if owner_gid is None else owner_gid
    request_path = absolute_path(str(request_path), "proxy request")
    raw_request, request_payload, request_info = read_private_json(
        request_path,
        label="proxy request",
        max_bytes=MAX_REQUEST_BYTES,
        owner_uid=uid,
    )
    request = parse_request(raw_request)
    validate_requested_metadata(request, owner_uid=uid, owner_gid=gid)
    state_root = Path(request["state_root"])
    if (
        state_root == request_path
        or state_root in request_path.parents
        or request_path in state_root.parents
    ):
        raise TransactionError(
            "invalid_manifest", "request path overlaps transaction state"
        )
    # Package/binary/identity provenance is a read-only preflight.  Run it
    # before creating even the protected state root, then repeat it under the
    # transaction lock to close the preflight-to-lock race.
    active_system = system if system is not None else ProxySystem(owner_uid=uid)
    preflight_provenance = validate_static_provenance(
        active_system.capture_static(request)
    )
    ensure_state_root(state_root, owner_uid=uid)
    with acquire_lock(state_root, owner_uid=uid, owner_gid=gid):
        locked_raw, locked_payload, locked_info = read_private_json(
            request_path,
            label="proxy request",
            max_bytes=MAX_REQUEST_BYTES,
            owner_uid=uid,
        )
        if (
            not hmac.compare_digest(request_payload, locked_payload)
            or request_info.st_dev != locked_info.st_dev
            or request_info.st_ino != locked_info.st_ino
            or request_info.st_mtime_ns != locked_info.st_mtime_ns
        ):
            raise TransactionError(
                "request_changed", "proxy request changed while locking"
            )
        request = parse_request(locked_raw)
        validate_requested_metadata(request, owner_uid=uid, owner_gid=gid)
        if load_current(state_root, owner_uid=uid, required=False) is not None:
            raise TransactionError(
                "current_generation", "a proxy generation is already applied"
            )

        provenance = active_system.capture_static(request)
        provenance = validate_static_provenance(provenance)
        if provenance != preflight_provenance:
            raise TransactionError(
                "provenance_drift", "proxy provenance changed before locking"
            )
        units_raw = active_system.capture_units()
        if not isinstance(units_raw, dict) or set(units_raw) != {
            "generic",
            "dedicated",
        }:
            raise TransactionError(
                "unit_state_failed", "proxy unit inventory is invalid"
            )
        units = {
            "generic": validate_unit_state(units_raw["generic"], dedicated=False),
            "dedicated": validate_unit_state(units_raw["dedicated"], dedicated=True),
        }
        sources = capture_sources(request, owner_uid=uid)
        targets = capture_targets(request, owner_uid=uid)
        if (
            targets["proxy_unit"]["state"]["existed"]
            and units["dedicated"]["enabled_state"] == "not-found"
        ):
            raise TransactionError(
                "unit_state_failed",
                "dedicated proxy unit inventory is stale; reconcile it before apply",
            )
        require_units(active_system, units)
        verify_boundary(active_system, provenance, boundary="before-state-prepare")

        generation = secrets.token_hex(16)
        state_dir = create_state_directory(state_root, generation, owner_uid=uid)
        document: dict[str, Any] | None = None
        manifest_payload: bytes | None = None
        try:
            document, manifest_payload = prepare_state(
                request,
                sha256_bytes(locked_payload),
                provenance,
                units,
                sources,
                targets,
                state_dir,
                generation,
                owner_uid=uid,
                owner_gid=gid,
            )
        except BaseException:
            if load_current(state_root, owner_uid=uid, required=False) is None:
                cleanup_uncommitted_state(state_dir, state_root=state_root)
            raise

        try:
            journal = apply_files(
                document,
                sources,
                targets,
                active_system,
                owner_uid=uid,
                owner_gid=gid,
            )
            journal, probes = run_apply_actions(
                document,
                journal,
                active_system,
                owner_uid=uid,
                owner_gid=gid,
            )
            for entry in document["files"]:
                if not optional_target_matches(
                    Path(entry["target"]),
                    {"existed": True, **entry["desired"]},
                    role=entry["role"],
                    owner_uid=uid,
                ):
                    raise TransactionError(
                        "install_verification_failed", "proxy install is incomplete"
                    )
            verify_desired_units(active_system)
            verify_boundary(active_system, provenance, boundary="before-applied")
            checkpoint(
                document,
                journal,
                phase="applied",
                intent=None,
                owner_uid=uid,
                owner_gid=gid,
            )
            return {
                "status": "applied",
                "generation": generation,
                "files_managed": len(ROLES),
                "package_mutated": False,
                "provenance_verified": True,
                "unit_state": {
                    "generic_disabled_inactive": True,
                    "dedicated_enabled_active": True,
                },
                "probes": probes,
            }
        except BaseException as original:
            error = _as_transaction_error(original)
            rollback: dict[str, Any]
            try:
                assert manifest_payload is not None
                restore_from_document(
                    document,
                    manifest_payload,
                    active_system,
                    owner_uid=uid,
                    owner_gid=gid,
                )
                rollback = {"attempted": True, "ok": True, "recovery_required": False}
            except BaseException:
                mark_recovery_required(document, owner_uid=uid, owner_gid=gid)
                rollback = {"attempted": True, "ok": False, "recovery_required": True}
            raise TransactionError(
                error.code, str(error), rollback=rollback
            ) from original


def restore_proxy_bundle(
    manifest_path: Path,
    *,
    system: Any | None = None,
    owner_uid: int | None = None,
    owner_gid: int | None = None,
) -> dict[str, Any]:
    uid = os.geteuid() if owner_uid is None else owner_uid
    gid = os.getegid() if owner_gid is None else owner_gid
    manifest_path = absolute_path(str(manifest_path), "proxy transaction manifest")
    document, manifest_payload = load_state_manifest(
        manifest_path, owner_uid=uid, owner_gid=gid
    )
    state_root = Path(document["state_root"])
    ensure_state_root(state_root, owner_uid=uid)
    with acquire_lock(state_root, owner_uid=uid, owner_gid=gid):
        locked_document, locked_payload = load_state_manifest(
            manifest_path, owner_uid=uid, owner_gid=gid
        )
        if not hmac.compare_digest(manifest_payload, locked_payload):
            raise TransactionError(
                "manifest_changed", "proxy manifest changed while locking"
            )
        active_system = system if system is not None else ProxySystem(owner_uid=uid)
        try:
            return restore_from_document(
                locked_document,
                locked_payload,
                active_system,
                owner_uid=uid,
                owner_gid=gid,
            )
        except BaseException as original:
            mark_recovery_required(locked_document, owner_uid=uid, owner_gid=gid)
            error = _as_transaction_error(original)
            raise TransactionError(
                error.code,
                str(error),
                rollback={"attempted": True, "ok": False, "recovery_required": True},
            ) from original


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--request", type=Path, required=True)
    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("--manifest", type=Path, required=True)
    return parser


def transaction_signal_handler(_signum: int, _frame: Any) -> None:
    raise TransactionError("interrupted", "proxy transaction was interrupted")


def install_signal_handlers() -> dict[int, Any]:
    previous: dict[int, Any] = {}
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        try:
            previous[number] = signal.getsignal(number)
            signal.signal(number, transaction_signal_handler)
        except (OSError, ValueError) as exc:
            raise TransactionError(
                "signal_failed", "transaction signal handling failed"
            ) from exc
    return previous


def restore_signal_handlers(previous: Mapping[int, Any]) -> None:
    for number, handler in previous.items():
        try:
            signal.signal(number, handler)
        except (OSError, ValueError):
            pass


def main(argv: Sequence[str] | None = None) -> int:
    previous: dict[int, Any] = {}
    try:
        arguments = build_parser().parse_args(argv)
        validate_runtime()
        previous = install_signal_handlers()
        if arguments.command == "apply":
            result = apply_proxy_bundle(arguments.request)
        else:
            result = restore_proxy_bundle(arguments.manifest)
        emit(result)
        return 0
    except TransactionError as exc:
        error: dict[str, Any] = {"code": exc.code, "message": str(exc)}
        if exc.rollback is not None:
            error["rollback"] = exc.rollback
        emit({"status": "error", "error": error}, stream=sys.stderr)
        return 1
    except BaseException:
        emit(
            {
                "status": "error",
                "error": {
                    "code": "internal_error",
                    "message": "unexpected internal proxy transaction failure",
                },
            },
            stream=sys.stderr,
        )
        return 1
    finally:
        restore_signal_handlers(previous)


if __name__ == "__main__":
    raise SystemExit(main())
