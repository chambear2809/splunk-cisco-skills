#!/usr/bin/env python3
"""Apply or restore the five-file Galileo Collector runtime bundle safely.

This command is deliberately narrow.  It runs only as root on Linux, accepts a
root-private declarative request, manages exactly five allowlisted file roles,
and operates one already-installed systemd Collector service.  It does not
install, remove, or configure tinyproxy and it does not modify Collector YAML.

Machine-readable output is fixed-schema sanitized JSON.  File contents,
credentials, paths, and subprocess output are never emitted.
"""

from __future__ import annotations

import argparse
import base64
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


REQUEST_SCHEMA = "galileo-runtime-bundle-request/v1"
STATE_SCHEMA = "galileo-runtime-bundle-state/v1"
JOURNAL_SCHEMA = "galileo-runtime-bundle-journal/v1"
CURRENT_SCHEMA = "galileo-runtime-bundle-current/v1"

ROLES = (
    "routing_env",
    "protected_evidence",
    "runtime_wrapper",
    "galileo_key",
    "collector_dropin",
)
APPLY_ORDER = ROLES
RESTORE_ORDER = tuple(reversed(ROLES))
ROLE_LIMITS = {
    "routing_env": 256 * 1024,
    "protected_evidence": 1024 * 1024,
    "runtime_wrapper": 4 * 1024 * 1024,
    "galileo_key": 64 * 1024,
    "collector_dropin": 256 * 1024,
}

RUNTIME_CONFIG_DIR = Path("/etc/splunk-otel-collector")
LIBEXEC_DIR = Path("/usr/local/libexec")
SYSTEMD_DIR = Path("/etc/systemd/system")
PYTHON_BINARY_PATH = Path("/usr/bin/python3")
COLLECTOR_BINARY_PATH = Path("/usr/bin/otelcol")
COLLECTOR_CONFIG_PATH = Path("/etc/splunk-otel-collector/lemonade-agent-config.yaml")
GALILEO_QUEUE_BASE_DIR = Path("/var/lib/splunk-otel-collector/galileo-queue")
COLLECTOR_SERVICE = "splunk-otel-collector.service"
GALILEO_PROXY_SERVICE = "galileo-tinyproxy.service"
GALILEO_PROXY_URL = "http://127.0.0.1:18888"
MACHINE_ID_PATHS = (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id"))
SYSTEMCTL_PATHS = ("/usr/bin/systemctl", "/bin/systemctl")
DPKG_QUERY = "/usr/bin/dpkg-query"
PACKAGE_ALLOWLIST = frozenset({"splunk-otel-collector"})

MAX_REQUEST_BYTES = 1024 * 1024
MAX_STATE_BYTES = 2 * 1024 * 1024
MAX_COLLECTOR_CONFIG_BYTES = 16 * 1024 * 1024
MAX_BINARY_BYTES = 1024 * 1024 * 1024
MAX_UNIT_BYTES = 8 * 1024 * 1024
MAX_XATTR_COUNT = 64
MAX_XATTR_BYTES = 64 * 1024
MAX_HEALTH_TIMEOUT = 30.0
DEFAULT_HEALTH_TIMEOUT = 15.0
MAX_COMMAND_OUTPUT = 32 * 1024

GENERATION_RE = re.compile(r"^[0-9a-f]{32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SERVICE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@:-]{0,254}$")
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
SAFE_VERSION_RE = re.compile(r"^[A-Za-z0-9.+:~_-]{1,256}$")
SAFE_IDENTITY_RE = re.compile(r"^[A-Za-z0-9_.@-]{0,255}$")
MODE_RE = re.compile(r"^0[0-7]{3}$")
EXEC_START_RE = re.compile(
    r"^\{\s*path=(?P<path>[^;]+?)\s*;\s*"
    r"argv\[\]=(?P<argv>.*?)\s*;\s*"
    r"ignore_errors=(?P<ignore>yes|no)\s*;[^{}]*\}$"
)

ROUTING_FIXED_KEYS = frozenset(
    {
        "GALILEO_OTLP_TRACES_ENDPOINT",
        "GALILEO_EXPECTED_ORIGIN",
        "GALILEO_API_KEY_FILE",
        "GALILEO_PROXY_URL",
        "GALILEO_TINYPROXY_EVIDENCE_FILE",
        "GALILEO_DESTINATION_FINGERPRINT",
        "GALILEO_QUEUE_STORAGE_DIRECTORY",
        "GALILEO_COLLECTOR_BINARY",
        "GALILEO_COLLECTOR_BINARY_SHA256",
    }
)
ROUTING_ID_KEYS = frozenset({"GALILEO_PROJECT_ID", "GALILEO_LOG_STREAM_ID"})
ROUTING_NAME_KEYS = frozenset({"GALILEO_PROJECT", "GALILEO_LOG_STREAM"})
ACCESS_ALTERING_XATTRS = frozenset(
    {"security.capability", "system.posix_acl_access", "system.posix_acl_default"}
)

SUBPROCESS_ENV = {
    "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG": "C",
    "LC_ALL": "C",
}


class TransactionError(RuntimeError):
    """An operational failure with a message safe to emit."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message


class JsonArgumentParser(argparse.ArgumentParser):
    """Prevent arbitrary rejected argv values from reaching stderr."""

    def error(self, _message: str) -> None:
        raise TransactionError("invalid_arguments", "command arguments are invalid")


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        raise TransactionError(
            "health_redirect", "collector health endpoint redirected"
        )


def emit(document: Mapping[str, Any], *, stream: Any = sys.stdout) -> None:
    stream.write(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")
    stream.flush()


def utc_now() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def json_bytes(document: Mapping[str, Any]) -> bytes:
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def reject_nonfinite_json(value: str) -> None:
    raise ValueError(f"non-finite JSON is forbidden: {value}")


def validate_runtime() -> None:
    if not sys.platform.startswith("linux"):
        raise TransactionError(
            "unsupported_platform", "apply and restore require Linux"
        )
    if os.geteuid() != 0:
        raise TransactionError("root_required", "apply and restore require root")


def absolute_path(value: Any, label: str) -> Path:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 4096
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        raise TransactionError("invalid_path", f"{label} path is invalid")
    path = Path(value)
    normalized = Path(os.path.normpath(value))
    if not path.is_absolute() or path != normalized or path == Path("/"):
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
        raise TransactionError(
            "invalid_manifest", "file mode must be a four-digit octal string"
        )
    return int(value, 8)


def validate_service_name(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not SERVICE_RE.fullmatch(value)
        or value.startswith("-")
    ):
        raise TransactionError("invalid_service", "systemd service name is invalid")
    return value


def validate_health_url(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 2048
        or "%" in value
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
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
            "invalid_health_url", "health URL must use a loopback IP literal"
        ) from exc
    if not host.is_loopback:
        raise TransactionError(
            "invalid_health_url", "health URL must use a loopback IP literal"
        )
    return value


def validate_timeout(value: Any) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
        or value > MAX_HEALTH_TIMEOUT
    ):
        raise TransactionError(
            "invalid_timeout",
            f"health timeout must be greater than zero and at most {MAX_HEALTH_TIMEOUT:g} seconds",
        )
    return float(value)


def valid_network_host(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        labels = host.split(".")
        return (
            len(host) <= 253
            and bool(labels)
            and all(
                label
                and len(label) <= 63
                and label[0].isascii()
                and label[0].isalnum()
                and label[-1].isascii()
                and label[-1].isalnum()
                and all(
                    character.isascii() and (character.isalnum() or character == "-")
                    for character in label
                )
                for label in labels
            )
        )


def parse_routing_environment(payload: bytes) -> dict[str, str]:
    try:
        text = payload.decode("ascii", errors="strict")
    except UnicodeDecodeError as exc:
        raise TransactionError(
            "invalid_routing_env", "routing environment must be strict ASCII"
        ) from exc
    if not text.endswith("\n") or text.endswith("\n\n") or "\r" in text:
        raise TransactionError(
            "invalid_routing_env",
            "routing environment must contain one assignment per line",
        )
    result: dict[str, str] = {}
    for line in text[:-1].split("\n"):
        if not line or line.count("=") != 1:
            raise TransactionError(
                "invalid_routing_env",
                "routing environment must contain one assignment per line",
            )
        name, value = line.split("=", 1)
        if (
            not re.fullmatch(r"[A-Z][A-Z0-9_]*", name)
            or name in result
            or not value
            or any(not 0x21 <= ord(character) <= 0x7E for character in value)
            or any(character in value for character in "#'\"\\")
        ):
            raise TransactionError(
                "invalid_routing_env", "routing environment assignment is invalid"
            )
        result[name] = value
    identifiers = ROUTING_FIXED_KEYS | ROUTING_ID_KEYS
    names = ROUTING_FIXED_KEYS | ROUTING_NAME_KEYS
    if frozenset(result) not in {identifiers, names}:
        raise TransactionError(
            "invalid_routing_env",
            "routing environment must contain exactly one selector contract",
        )
    return result


def canonical_routing_endpoint(value: str) -> tuple[str, str]:
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise TransactionError(
            "invalid_routing_env", "Galileo routing endpoint is invalid"
        ) from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or not parsed.path.startswith("/")
        or not parsed.path.strip("/")
        or ";" in parsed.path
        or "%" in parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise TransactionError(
            "invalid_routing_env", "Galileo routing endpoint is invalid"
        )
    host = parsed.hostname.casefold()
    if host.endswith(".") or not valid_network_host(host):
        raise TransactionError(
            "invalid_routing_env", "Galileo routing endpoint is invalid"
        )
    if any(segment in {".", ".."} for segment in parsed.path.split("/")):
        raise TransactionError(
            "invalid_routing_env", "Galileo routing endpoint is invalid"
        )
    host_for_url = f"[{host}]" if ":" in host else host
    origin = f"https://{host_for_url}"
    canonical = f"{origin}{parsed.path}"
    if value != canonical:
        raise TransactionError(
            "invalid_routing_env", "Galileo routing endpoint must be canonical"
        )
    return origin, canonical


def validate_routing_environment_contract(
    request: Mapping[str, Any], sources: Mapping[str, Mapping[str, Any]]
) -> None:
    routing = request["files"]["routing_env"]
    if routing["action"] == "remove":
        return
    key = request["files"]["galileo_key"]
    evidence = request["files"]["protected_evidence"]
    if key["action"] != "install" or evidence["action"] != "install":
        raise TransactionError(
            "invalid_routing_env",
            "routing environment dependencies must be installed in the same bundle",
        )
    payload = sources["routing_env"].get("payload")
    if not isinstance(payload, bytes):
        raise TransactionError(
            "invalid_routing_env", "routing environment source is invalid"
        )
    environment = parse_routing_environment(payload)
    if (
        environment["GALILEO_API_KEY_FILE"] != key["target"]
        or environment["GALILEO_TINYPROXY_EVIDENCE_FILE"] != evidence["target"]
        or environment["GALILEO_PROXY_URL"] != GALILEO_PROXY_URL
        or environment["GALILEO_COLLECTOR_BINARY"]
        != request["provenance"]["collector_binary"]
        or environment["GALILEO_COLLECTOR_BINARY_SHA256"]
        != request["provenance"]["collector_binary_sha256"]
    ):
        raise TransactionError(
            "invalid_routing_env", "routing environment paths are not bound"
        )
    origin, endpoint = canonical_routing_endpoint(
        environment["GALILEO_OTLP_TRACES_ENDPOINT"]
    )
    if environment["GALILEO_EXPECTED_ORIGIN"] != origin:
        raise TransactionError(
            "invalid_routing_env", "Galileo endpoint and expected origin differ"
        )
    if ROUTING_ID_KEYS <= environment.keys():
        selector = (
            "ids",
            environment["GALILEO_PROJECT_ID"],
            environment["GALILEO_LOG_STREAM_ID"],
        )
    else:
        selector = (
            "names",
            environment["GALILEO_PROJECT"],
            environment["GALILEO_LOG_STREAM"],
        )
    fingerprint = sha256_bytes(
        json.dumps(
            {
                "endpoint": endpoint,
                "log_stream": selector[2],
                "project": selector[1],
                "selector_kind": selector[0],
                "version": 1,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    if not hmac.compare_digest(
        environment["GALILEO_DESTINATION_FINGERPRINT"], fingerprint
    ):
        raise TransactionError(
            "invalid_routing_env", "Galileo destination fingerprint is invalid"
        )
    try:
        queue = absolute_path(
            environment["GALILEO_QUEUE_STORAGE_DIRECTORY"], "Galileo queue"
        )
    except TransactionError as exc:
        raise TransactionError(
            "invalid_routing_env", "Galileo queue path is invalid"
        ) from exc
    if queue.parent != GALILEO_QUEUE_BASE_DIR or queue.name != fingerprint:
        raise TransactionError(
            "invalid_routing_env", "Galileo queue path is not destination-bound"
        )


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
    """Require canonical nonlinked ancestors owned by root/tool owner."""

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
                "unsafe_path", f"{label} path cannot be inspected"
            ) from exc
        if stat.S_ISLNK(info.st_mode):
            raise TransactionError("unsafe_path", f"{label} path contains a symlink")
        if index < final_index and not stat.S_ISDIR(info.st_mode):
            raise TransactionError(
                "unsafe_path", f"{label} ancestor is not a directory"
            )
        mode = stat.S_IMODE(info.st_mode)
        # A root-owned sticky directory such as /tmp is safe solely as an
        # already-existing traversal ancestor: sticky semantics prevent an
        # untrusted principal from replacing another owner's descendant.
        sticky_root_ancestor = (
            index < final_index
            and stat.S_ISDIR(info.st_mode)
            and info.st_uid == 0
            and bool(info.st_mode & stat.S_ISVTX)
        )
        if (
            not sticky_root_ancestor
            and (info.st_uid not in {0, owner_uid} or mode & 0o022)
        ):
            raise TransactionError(
                "unsafe_path",
                f"{label} ancestors must be trusted and not group/other-writable",
            )


def assert_private_directory(path: Path, *, owner_uid: int, label: str) -> None:
    assert_trusted_path(path, label=label, owner_uid=owner_uid, include_final=True)
    info = os.lstat(path)
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != owner_uid
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise TransactionError(
            "unsafe_directory", f"{label} must be owner-only mode 0700"
        )


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
            "fsync_failed", "transaction state could not be synchronized"
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
            "state_root_failed", "transaction state root could not be created"
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
    path: Path, payload: bytes, *, mode: int, owner_uid: int, owner_gid: int
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
            "state_write_failed", "transaction state could not be written"
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
            "state_write_failed", "transaction state could not be created"
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
    except TransactionError:
        raise
    except OSError as exc:
        raise TransactionError(
            "state_write_failed", "transaction state could not be synchronized"
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
            raise TransactionError(
                "unsafe_file", f"{label} must be a single-link regular file"
            )
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
        raise TransactionError("unsafe_file", f"{label} must be owner-only mode 0600")
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
        raise TransactionError("invalid_manifest", f"{label} must be a JSON object")
    return document, payload, info


def read_xattrs(path: Path, info: os.stat_result, *, label: str) -> dict[str, bytes]:
    if not all(
        callable(getattr(os, name, None))
        for name in ("listxattr", "getxattr", "setxattr", "removexattr")
    ):
        if sys.platform.startswith("linux"):
            raise TransactionError(
                "metadata_unsupported", "extended-attribute support is required"
            )
        return {}
    try:
        names = os.listxattr(path, follow_symlinks=False)
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
            value = os.getxattr(path, name, follow_symlinks=False)
        except OSError as exc:
            raise TransactionError(
                "metadata_read_failed", f"{label} extended attributes changed"
            ) from exc
        total += len(name.encode("utf-8")) + len(value)
        if total > MAX_XATTR_BYTES:
            raise TransactionError(
                "metadata_too_large", f"{label} extended attributes exceed the limit"
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
        total += len(name.encode("utf-8")) + len(payload)
        if total > MAX_XATTR_BYTES:
            raise TransactionError("invalid_state", "file metadata snapshot is invalid")
        result[name] = payload
    return result


def apply_xattrs(path: Path, expected: Mapping[str, bytes]) -> None:
    if not all(
        callable(getattr(os, name, None))
        for name in ("listxattr", "getxattr", "setxattr", "removexattr")
    ):
        if expected or sys.platform.startswith("linux"):
            raise TransactionError(
                "metadata_unsupported", "extended-attribute support is required"
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
            "metadata_restore_failed", "file extended attributes cannot be restored"
        ) from exc


def file_state(
    path: Path, *, label: str, max_bytes: int, owner_uid: int
) -> tuple[dict[str, Any], bytes, os.stat_result]:
    payload, info = read_regular_file(
        path, label=label, max_bytes=max_bytes, owner_uid=owner_uid
    )
    xattrs = read_xattrs(path, info, label=label)
    state = {
        "sha256": sha256_bytes(payload),
        "uid": info.st_uid,
        "gid": info.st_gid,
        "mode": stat.S_IMODE(info.st_mode),
        "size": len(payload),
        "xattrs": encode_xattrs(xattrs),
    }
    return state, payload, info


def state_metadata(value: Any, *, allow_size: int) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "sha256",
        "uid",
        "gid",
        "mode",
        "size",
        "xattrs",
    }:
        raise TransactionError("invalid_state", "file state snapshot is invalid")
    sha256 = validate_sha256(value["sha256"], "file state")
    uid = validate_nonnegative_integer(value["uid"], "file owner")
    gid = validate_nonnegative_integer(value["gid"], "file group")
    mode = validate_nonnegative_integer(value["mode"], "file mode")
    size = validate_nonnegative_integer(value["size"], "file size")
    if mode > 0o7777 or size > allow_size:
        raise TransactionError("invalid_state", "file state snapshot is invalid")
    xattrs = decode_xattrs(value["xattrs"])
    return {
        "sha256": sha256,
        "uid": uid,
        "gid": gid,
        "mode": mode,
        "size": size,
        "xattrs": encode_xattrs(xattrs),
    }


def states_equal(first: Mapping[str, Any], second: Mapping[str, Any]) -> bool:
    return (
        hmac.compare_digest(str(first["sha256"]), str(second["sha256"]))
        and first["uid"] == second["uid"]
        and first["gid"] == second["gid"]
        and first["mode"] == second["mode"]
        and first["size"] == second["size"]
        and first["xattrs"] == second["xattrs"]
    )


def inspect_optional_target(
    path: Path, *, role: str, owner_uid: int
) -> tuple[dict[str, Any], bytes | None, os.stat_result | None]:
    assert_trusted_path(
        path.parent,
        label="bundle target parent",
        owner_uid=owner_uid,
        include_final=True,
    )
    if not stat.S_ISDIR(os.lstat(path.parent).st_mode):
        raise TransactionError(
            "unsafe_path", "bundle target parent must be a directory"
        )
    try:
        os.lstat(path)
    except FileNotFoundError:
        return {"existed": False}, None, None
    state, payload, info = file_state(
        path,
        label="existing bundle target",
        max_bytes=ROLE_LIMITS[role],
        owner_uid=owner_uid,
    )
    if stat.S_IMODE(info.st_mode) & 0o022:
        raise TransactionError(
            "unsafe_file", "existing bundle target is group/other-writable"
        )
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
        label="bundle target",
        max_bytes=ROLE_LIMITS[role],
        owner_uid=owner_uid,
    )
    return states_equal(actual, expected)


def before_target_commit(_role: str, _operation: str) -> None:
    """Test seam immediately before a target's final unlink/rename check."""


def before_source_recheck(_role: str) -> None:
    """Test seam immediately before an install source is re-read."""


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
        label="bundle target parent",
        owner_uid=owner_uid,
        include_final=True,
    )
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent
        )
    except OSError as exc:
        raise TransactionError(
            "install_failed", "bundle target temporary file could not be created"
        ) from exc
    temporary = Path(temporary_name)
    installed = False
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise TransactionError(
                "unsafe_file", "bundle target temporary file is unsafe"
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
                "metadata_restore_failed", "bundle target metadata is incorrect"
            )
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        before_target_commit(role, "install")
        if not optional_target_matches(
            path, expected_current, role=role, owner_uid=owner_uid
        ):
            raise TransactionError(
                "target_changed", "bundle target changed before installation"
            )
        os.replace(temporary, path)
        installed = True
        fsync_directory(path.parent)
    except TransactionError:
        raise
    except OSError as exc:
        raise TransactionError(
            "install_failed", "bundle target could not be installed atomically"
        ) from exc
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
        raise TransactionError("target_changed", "bundle target changed before removal")
    if expected_current.get("existed") is False:
        return
    try:
        os.unlink(path)
        fsync_directory(path.parent)
    except OSError as exc:
        raise TransactionError(
            "remove_failed", "bundle target could not be removed"
        ) from exc


def verify_installed(
    path: Path, expected: Mapping[str, Any], *, role: str, owner_uid: int
) -> None:
    if not optional_target_matches(
        path, {"existed": True, **expected}, role=role, owner_uid=owner_uid
    ):
        raise TransactionError(
            "install_verification_failed", "bundle target verification failed"
        )


def validate_target_path(role: str, path: Path, service: str) -> None:
    if not SAFE_NAME_RE.fullmatch(path.name):
        raise TransactionError("invalid_path", "bundle target filename is invalid")
    if role in {"routing_env", "protected_evidence"}:
        if path.parent != RUNTIME_CONFIG_DIR:
            raise TransactionError(
                "invalid_path",
                "runtime data target is outside its allowlisted directory",
            )
        suffix = {
            "routing_env": ".env",
            "protected_evidence": ".json",
        }[role]
        if not path.name.endswith(suffix):
            raise TransactionError(
                "invalid_path", "runtime data target has an invalid suffix"
            )
    elif role == "galileo_key":
        if (
            path.parent != RUNTIME_CONFIG_DIR / "secrets"
            or path.name != "galileo_api_key"
        ):
            raise TransactionError(
                "invalid_path", "Galileo key target is outside its allowlist"
            )
    elif role == "runtime_wrapper":
        if path.parent != LIBEXEC_DIR or not path.name.endswith(".py"):
            raise TransactionError(
                "invalid_path", "runtime wrapper target is outside its allowlist"
            )
    elif role == "collector_dropin":
        if path.parent != SYSTEMD_DIR / f"{service}.d" or not path.name.endswith(
            ".conf"
        ):
            raise TransactionError(
                "invalid_path", "collector drop-in target is outside its allowlist"
            )
    else:
        raise TransactionError("invalid_manifest", "bundle role is invalid")


def parse_request(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict) or set(document) != {
        "schema_version",
        "state_root",
        "service",
        "provenance",
        "files",
    }:
        raise TransactionError("invalid_manifest", "bundle request is invalid")
    if document.get("schema_version") != REQUEST_SCHEMA:
        raise TransactionError("invalid_manifest", "bundle request schema is invalid")
    state_root = absolute_path(document["state_root"], "state root")
    service_value = document["service"]
    if not isinstance(service_value, dict) or set(service_value) != {
        "name",
        "health_url",
        "health_timeout_seconds",
    }:
        raise TransactionError("invalid_manifest", "service request is invalid")
    service_name = validate_service_name(service_value["name"])
    if service_name != COLLECTOR_SERVICE:
        raise TransactionError(
            "invalid_service", "collector service is outside its allowlist"
        )
    service = {
        "name": service_name,
        "health_url": validate_health_url(service_value["health_url"]),
        "health_timeout_seconds": validate_timeout(
            service_value["health_timeout_seconds"]
        ),
    }
    provenance_value = document["provenance"]
    if not isinstance(provenance_value, dict) or set(provenance_value) != {
        "package_name",
        "package_version",
        "collector_binary",
        "collector_binary_sha256",
        "collector_config_sha256",
        "unit_fragment_sha256",
    }:
        raise TransactionError("invalid_manifest", "provenance request is invalid")
    package = provenance_value["package_name"]
    version = provenance_value["package_version"]
    if package not in PACKAGE_ALLOWLIST:
        raise TransactionError(
            "invalid_manifest", "collector package is not allowlisted"
        )
    if not isinstance(version, str) or not SAFE_VERSION_RE.fullmatch(version):
        raise TransactionError(
            "invalid_manifest", "collector package version is invalid"
        )
    collector_binary = absolute_path(
        provenance_value["collector_binary"], "collector binary"
    )
    if collector_binary != COLLECTOR_BINARY_PATH:
        raise TransactionError(
            "invalid_manifest", "collector binary path is outside its allowlist"
        )
    provenance = {
        "package_name": package,
        "package_version": version,
        "collector_binary": str(collector_binary),
        "collector_binary_sha256": validate_sha256(
            provenance_value["collector_binary_sha256"], "collector binary"
        ),
        "collector_config_sha256": validate_sha256(
            provenance_value["collector_config_sha256"], "collector config"
        ),
        "unit_fragment_sha256": validate_sha256(
            provenance_value["unit_fragment_sha256"], "systemd unit fragment"
        ),
    }

    files_value = document["files"]
    if not isinstance(files_value, list) or len(files_value) != len(ROLES):
        raise TransactionError(
            "invalid_manifest", "bundle request must contain exactly five files"
        )
    files: dict[str, dict[str, Any]] = {}
    for raw in files_value:
        if not isinstance(raw, dict):
            raise TransactionError("invalid_manifest", "bundle file entry is invalid")
        role = raw.get("role")
        action = raw.get("action")
        if role not in ROLES or role in files or action not in {"install", "remove"}:
            raise TransactionError("invalid_manifest", "bundle file entry is invalid")
        target = absolute_path(raw.get("target"), "bundle target")
        validate_target_path(role, target, service["name"])
        if action == "remove":
            if set(raw) != {"role", "action", "target"}:
                raise TransactionError(
                    "invalid_manifest", "remove entry contains unsupported fields"
                )
            files[role] = {"role": role, "action": action, "target": str(target)}
            continue
        if set(raw) != {
            "role",
            "action",
            "source",
            "target",
            "sha256",
            "uid",
            "gid",
            "mode",
        }:
            raise TransactionError(
                "invalid_manifest", "install entry contains unsupported fields"
            )
        source = absolute_path(raw["source"], "staged source")
        files[role] = {
            "role": role,
            "action": action,
            "source": str(source),
            "target": str(target),
            "sha256": validate_sha256(raw["sha256"], "staged source"),
            "uid": validate_nonnegative_integer(raw["uid"], "staged owner"),
            "gid": validate_nonnegative_integer(raw["gid"], "staged group"),
            "mode": validate_mode(raw["mode"]),
        }
    if set(files) != set(ROLES):
        raise TransactionError(
            "invalid_manifest", "bundle request must declare every allowlisted role"
        )
    targets = [entry["target"] for entry in files.values()]
    sources = [entry["source"] for entry in files.values() if "source" in entry]
    if len(set(targets)) != len(targets) or len(set(sources)) != len(sources):
        raise TransactionError("invalid_manifest", "bundle paths must be distinct")
    if set(targets) & set(sources):
        raise TransactionError("invalid_manifest", "source and target paths overlap")
    for path_value in (*targets, *sources):
        path = Path(path_value)
        if (
            state_root == path
            or state_root in path.parents
            or path in state_root.parents
        ):
            raise TransactionError(
                "invalid_manifest", "state root must not overlap bundle paths"
            )
    return {
        "schema_version": REQUEST_SCHEMA,
        "state_root": str(state_root),
        "service": service,
        "provenance": provenance,
        "files": files,
    }


def validate_role_metadata(
    request: Mapping[str, Any],
    provenance: Mapping[str, Any],
    *,
    root_uid: int,
    root_gid: int,
) -> None:
    unit = provenance.get("unit")
    if not isinstance(unit, dict):
        raise TransactionError("provenance_failed", "service identity is unavailable")
    service_uid = unit.get("service_uid")
    service_gid = unit.get("service_gid")
    if (
        isinstance(service_uid, bool)
        or not isinstance(service_uid, int)
        or service_uid < 0
        or isinstance(service_gid, bool)
        or not isinstance(service_gid, int)
        or service_gid < 0
    ):
        raise TransactionError("provenance_failed", "service identity is unavailable")
    expected = {
        "routing_env": (root_uid, root_gid, 0o600),
        "protected_evidence": (root_uid, service_gid, 0o440),
        "runtime_wrapper": (root_uid, root_gid, 0o755),
        "galileo_key": (service_uid, service_gid, 0o600),
        "collector_dropin": (root_uid, root_gid, 0o644),
    }
    for role in ROLES:
        entry = request["files"][role]
        if entry["action"] != "install":
            continue
        observed = (entry["uid"], entry["gid"], entry["mode"])
        if observed != expected[role]:
            if role == "protected_evidence":
                raise TransactionError(
                    "evidence_unreadable",
                    "protected evidence must be root-owned, collector-grouped, and mode 0440",
                )
            raise TransactionError(
                "invalid_metadata", f"{role} ownership or mode is not allowlisted"
            )


def validate_secret_directory(provenance: Mapping[str, Any], *, root_uid: int) -> None:
    unit = provenance.get("unit")
    if not isinstance(unit, dict):
        raise TransactionError("provenance_failed", "service identity is unavailable")
    service_gid = unit.get("service_gid")
    if isinstance(service_gid, bool) or not isinstance(service_gid, int):
        raise TransactionError("provenance_failed", "service identity is unavailable")
    path = RUNTIME_CONFIG_DIR / "secrets"
    assert_trusted_path(
        path,
        label="Galileo secrets directory",
        owner_uid=root_uid,
        include_final=True,
    )
    info = os.lstat(path)
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != root_uid
        or info.st_gid != service_gid
        or stat.S_IMODE(info.st_mode) != 0o750
    ):
        raise TransactionError(
            "unsafe_secret_directory",
            "Galileo secrets directory must be root-owned, collector-grouped, and mode 0750",
        )


def validate_dropin_contract(
    request: Mapping[str, Any], sources: Mapping[str, Mapping[str, Any]]
) -> None:
    dropin = request["files"]["collector_dropin"]
    if dropin["action"] == "remove":
        return
    routing = request["files"]["routing_env"]
    wrapper = request["files"]["runtime_wrapper"]
    if routing["action"] != "install" or wrapper["action"] != "install":
        raise TransactionError(
            "invalid_dropin",
            "collector drop-in dependencies must be installed in the same bundle",
        )
    if Path(request["provenance"]["collector_binary"]) != COLLECTOR_BINARY_PATH:
        raise TransactionError(
            "invalid_dropin", "collector drop-in binary target is invalid"
        )
    expected = (
        "[Unit]\n"
        f"Wants={GALILEO_PROXY_SERVICE}\n"
        f"After={GALILEO_PROXY_SERVICE}\n"
        "\n"
        "[Service]\n"
        f"EnvironmentFile={routing['target']}\n"
        "ExecStart=\n"
        f"ExecStart={PYTHON_BINARY_PATH} {wrapper['target']} -- "
        f"{COLLECTOR_BINARY_PATH} "
        f"--config={COLLECTOR_CONFIG_PATH}\n"
    ).encode("utf-8")
    payload = sources["collector_dropin"]["payload"]
    if not isinstance(payload, bytes) or not hmac.compare_digest(payload, expected):
        raise TransactionError(
            "invalid_dropin",
            "collector drop-in does not match the exact runtime command contract",
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
            "command_failed", "required local command could not be executed"
        ) from exc
    if len(result.stdout.encode("utf-8")) > MAX_COMMAND_OUTPUT:
        raise TransactionError(
            "command_failed", "required local command output is invalid"
        )
    return result


def systemctl_path() -> str:
    for candidate in SYSTEMCTL_PATHS:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    raise TransactionError("systemctl_missing", "systemctl is not available")


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
        return sha256_bytes(b"galileo-runtime-host-v1\0" + stripped)
    raise TransactionError(
        "host_identity_failed", "host identity could not be verified"
    )


def package_version(package: str) -> str:
    if package not in PACKAGE_ALLOWLIST:
        raise TransactionError("package_failed", "collector package is not allowlisted")
    if not (os.path.isfile(DPKG_QUERY) and os.access(DPKG_QUERY, os.X_OK)):
        raise TransactionError(
            "package_failed", "collector package version cannot be verified"
        )
    result = run_command((DPKG_QUERY, "-W", "-f=${Version}", "--", package))
    version = result.stdout.strip()
    if result.returncode != 0 or not SAFE_VERSION_RE.fullmatch(version):
        raise TransactionError(
            "package_failed", "collector package version cannot be verified"
        )
    return version


def binary_provenance(
    path: Path, *, owner_uid: int, max_bytes: int, label: str
) -> dict[str, Any]:
    assert_trusted_path(path, label=label, owner_uid=owner_uid, include_final=True)
    state, _payload, info = file_state(
        path, label=label, max_bytes=max_bytes, owner_uid=owner_uid
    )
    if (
        info.st_uid != 0
        or stat.S_IMODE(info.st_mode) & 0o022
        or not stat.S_IMODE(info.st_mode) & 0o111
    ):
        raise TransactionError(
            "provenance_failed", f"{label} is not a protected executable"
        )
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


def collector_config_provenance(path: Path, *, owner_uid: int) -> dict[str, Any]:
    if path != COLLECTOR_CONFIG_PATH:
        raise TransactionError(
            "provenance_failed", "collector config path is outside its allowlist"
        )
    assert_trusted_path(
        path,
        label="collector config",
        owner_uid=owner_uid,
        include_final=True,
    )
    state, _payload, info = file_state(
        path,
        label="collector config",
        max_bytes=MAX_COLLECTOR_CONFIG_BYTES,
        owner_uid=owner_uid,
    )
    if ACCESS_ALTERING_XATTRS & decode_xattrs(state["xattrs"]).keys():
        raise TransactionError(
            "provenance_failed", "collector config has access-altering metadata"
        )
    if (
        info.st_uid != owner_uid
        or info.st_gid != 0
        or stat.S_IMODE(info.st_mode) != 0o644
    ):
        raise TransactionError(
            "provenance_failed",
            "collector config must be root-owned, root-grouped, and mode 0644",
        )
    return {
        "path": str(path),
        "sha256": state["sha256"],
        "uid": state["uid"],
        "gid": state["gid"],
        "mode": state["mode"],
        "size": state["size"],
    }


def unit_file_provenance(path: Path, *, owner_uid: int, label: str) -> dict[str, Any]:
    assert_trusted_path(path, label=label, owner_uid=owner_uid, include_final=True)
    state, _payload, info = file_state(
        path, label=label, max_bytes=MAX_UNIT_BYTES, owner_uid=owner_uid
    )
    if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
        raise TransactionError(
            "provenance_failed", "systemd unit file is not protected"
        )
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


def resolve_service_identity(user_name: str, group_name: str) -> tuple[int, int]:
    if not SAFE_IDENTITY_RE.fullmatch(user_name) or not SAFE_IDENTITY_RE.fullmatch(
        group_name
    ):
        raise TransactionError(
            "service_identity_failed", "collector service identity is invalid"
        )
    try:
        if user_name:
            user_record = pwd.getpwnam(user_name)
            uid = user_record.pw_uid
            primary_gid = user_record.pw_gid
        else:
            uid = 0
            primary_gid = 0
        gid = grp.getgrnam(group_name).gr_gid if group_name else primary_gid
    except KeyError as exc:
        raise TransactionError(
            "service_identity_failed", "collector service identity cannot be resolved"
        ) from exc
    return uid, gid


def systemd_properties(systemctl: str, service: str) -> dict[str, str]:
    names = (
        "Id,LoadState,ActiveState,UnitFileState,FragmentPath,DropInPaths,"
        "User,Group,ExecStart,Wants,After"
    )
    result = run_command((systemctl, "show", f"--property={names}", "--", service))
    if result.returncode != 0:
        raise TransactionError(
            "service_metadata_failed", "collector service metadata is unavailable"
        )
    expected = set(names.split(","))
    selected: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        if not separator or key not in expected or key in selected:
            raise TransactionError(
                "service_metadata_failed", "collector service metadata is invalid"
            )
        if len(value) > 8192 or any(
            ord(character) < 0x20 or ord(character) == 0x7F for character in value
        ):
            raise TransactionError(
                "service_metadata_failed", "collector service metadata is invalid"
            )
        selected[key] = value
    if set(selected) != expected:
        raise TransactionError(
            "service_metadata_failed", "collector service metadata is incomplete"
        )
    if selected["Id"] != service or selected["LoadState"] != "loaded":
        raise TransactionError(
            "service_metadata_failed", "collector service is not exactly loaded"
        )
    return selected


def require_effective_execstart(value: str, wrapper: Path) -> None:
    match = EXEC_START_RE.fullmatch(value)
    expected_argv = (
        f"{PYTHON_BINARY_PATH} {wrapper} -- {COLLECTOR_BINARY_PATH} "
        f"--config={COLLECTOR_CONFIG_PATH}"
    )
    if (
        match is None
        or match.group("path").strip() != str(PYTHON_BINARY_PATH)
        or match.group("argv").strip() != expected_argv
        or match.group("ignore") != "no"
    ):
        raise TransactionError(
            "effective_unit_mismatch",
            "collector effective ExecStart does not match the runtime contract",
        )


def stable_unit_provenance(
    systemctl: str,
    service: str,
    managed_dropin: Path,
    *,
    owner_uid: int,
) -> tuple[dict[str, Any], str]:
    properties = systemd_properties(systemctl, service)
    fragment = absolute_path(properties["FragmentPath"], "systemd unit fragment")
    service_uid, service_gid = resolve_service_identity(
        properties["User"], properties["Group"]
    )
    raw_dropins = properties["DropInPaths"].split() if properties["DropInPaths"] else []
    if len(raw_dropins) > 128 or len(set(raw_dropins)) != len(raw_dropins):
        raise TransactionError(
            "service_metadata_failed", "collector drop-in inventory is invalid"
        )
    unmanaged: list[dict[str, Any]] = []
    for raw_path in sorted(raw_dropins):
        path = absolute_path(raw_path, "systemd drop-in")
        if path == managed_dropin:
            continue
        raise TransactionError(
            "unmanaged_dropin",
            "collector service has an unmanaged systemd drop-in",
        )
    return (
        {
            "name": service,
            "unit_file_state": properties["UnitFileState"],
            "user": properties["User"],
            "group": properties["Group"],
            "service_uid": service_uid,
            "service_gid": service_gid,
            "fragment": unit_file_provenance(
                fragment, owner_uid=owner_uid, label="systemd unit fragment"
            ),
            "unmanaged_dropins": unmanaged,
        },
        properties["ActiveState"],
    )


class RuntimeSystem:
    """Local systemd/package/health facade used by the transaction."""

    def __init__(self, *, owner_uid: int = 0) -> None:
        self.owner_uid = owner_uid
        self.systemctl = systemctl_path()

    def _snapshot(
        self,
        *,
        service: str,
        package: str,
        collector_binary: Path,
        managed_dropin: Path,
    ) -> tuple[dict[str, Any], str]:
        unit, active_state = stable_unit_provenance(
            self.systemctl,
            service,
            managed_dropin,
            owner_uid=self.owner_uid,
        )
        return (
            {
                "host_fingerprint": host_fingerprint(owner_uid=self.owner_uid),
                "package": {
                    "name": package,
                    "version": package_version(package),
                },
                "collector_binary": binary_provenance(
                    collector_binary,
                    owner_uid=self.owner_uid,
                    max_bytes=MAX_BINARY_BYTES,
                    label="collector binary",
                ),
                "collector_config": collector_config_provenance(
                    COLLECTOR_CONFIG_PATH,
                    owner_uid=self.owner_uid,
                ),
                "unit": unit,
            },
            active_state,
        )

    def capture(
        self, request: Mapping[str, Any], *, managed_dropin: Path
    ) -> dict[str, Any]:
        expected = request["provenance"]
        snapshot, active_state = self._snapshot(
            service=request["service"]["name"],
            package=expected["package_name"],
            collector_binary=Path(expected["collector_binary"]),
            managed_dropin=managed_dropin,
        )
        if active_state != "active":
            raise TransactionError(
                "service_not_active", "collector service must initially be active"
            )
        if snapshot["package"]["version"] != expected["package_version"]:
            raise TransactionError(
                "package_drift", "collector package version does not match the request"
            )
        if not hmac.compare_digest(
            snapshot["collector_binary"]["sha256"],
            expected["collector_binary_sha256"],
        ):
            raise TransactionError(
                "collector_binary_drift", "collector binary does not match the request"
            )
        if not hmac.compare_digest(
            snapshot["collector_config"]["sha256"],
            expected["collector_config_sha256"],
        ):
            raise TransactionError(
                "collector_config_drift", "collector config does not match the request"
            )
        if not hmac.compare_digest(
            snapshot["unit"]["fragment"]["sha256"],
            expected["unit_fragment_sha256"],
        ):
            raise TransactionError(
                "unit_drift", "collector unit fragment does not match the request"
            )
        return snapshot

    def verify(self, expected: Mapping[str, Any], *, managed_dropin: Path) -> None:
        actual, _active_state = self._snapshot(
            service=expected["unit"]["name"],
            package=expected["package"]["name"],
            collector_binary=Path(expected["collector_binary"]["path"]),
            managed_dropin=managed_dropin,
        )
        if actual != expected:
            raise TransactionError(
                "provenance_drift",
                "host, package, collector binary, or systemd provenance changed",
            )

    def verify_runtime_contract(
        self,
        *,
        service: str,
        managed_dropin: Path,
        wrapper: Path,
    ) -> None:
        properties = systemd_properties(self.systemctl, service)
        dropins = properties["DropInPaths"].split() if properties["DropInPaths"] else []
        if dropins != [str(managed_dropin)]:
            raise TransactionError(
                "effective_unit_mismatch",
                "collector effective drop-in inventory is not exact",
            )
        require_effective_execstart(properties["ExecStart"], wrapper)
        for dependency_property in ("Wants", "After"):
            dependencies = properties[dependency_property].split()
            if dependencies.count(GALILEO_PROXY_SERVICE) != 1:
                raise TransactionError(
                    "effective_unit_mismatch",
                    "collector effective proxy dependency is missing",
                )

    def daemon_reload(self, service: str) -> None:
        del service
        result = run_command((self.systemctl, "daemon-reload"))
        if result.returncode != 0:
            raise TransactionError(
                "daemon_reload_failed", "systemd daemon-reload failed"
            )

    def restart(self, service: str) -> None:
        result = run_command((self.systemctl, "restart", "--", service))
        if result.returncode != 0:
            raise TransactionError(
                "service_restart_failed", "collector service restart failed"
            )
        properties = systemd_properties(self.systemctl, service)
        if properties["ActiveState"] != "active":
            raise TransactionError(
                "service_restart_failed", "collector service did not become active"
            )

    def health(self, url: str, timeout: float) -> dict[str, Any]:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirectHandler()
        )
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "*/*",
                "Accept-Encoding": "identity",
                "User-Agent": "galileo-runtime-bundle-transaction/1",
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
                    response.close()
                if 200 <= last_status < 300:
                    return {"checked": True, "ok": True, "status_code": last_status}
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(0.25, remaining))
        result: dict[str, Any] = {"checked": True, "ok": False}
        if last_status is not None:
            result["status_code"] = last_status
        error = TransactionError(
            "health_failed", "collector loopback health check failed"
        )
        error.health = result  # type: ignore[attr-defined]
        raise error


def before_provenance_check(_boundary: str) -> None:
    """Test seam before every action-boundary provenance verification."""


def verify_boundary(
    system: Any,
    provenance: Mapping[str, Any],
    *,
    managed_dropin: Path,
    boundary: str,
) -> None:
    before_provenance_check(boundary)
    system.verify(provenance, managed_dropin=managed_dropin)


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
        raise TransactionError(
            "lock_failed", "transaction lock could not be opened"
        ) from exc
    try:
        info = os.fstat(descriptor)
        named = os.lstat(path)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != owner_uid
            or info.st_gid != owner_gid
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_dev != named.st_dev
            or info.st_ino != named.st_ino
        ):
            raise TransactionError("unsafe_lock", "transaction lock is unsafe")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise TransactionError(
                "transaction_busy", "another runtime-bundle transaction is active"
            ) from exc
        return os.fdopen(descriptor, "r+b", closefd=True)
    except BaseException:
        os.close(descriptor)
        raise


def create_state_directory(
    state_root: Path, generation: str, *, owner_uid: int, owner_gid: int
) -> Path:
    directory = state_root / f"generation-{generation}"
    try:
        os.mkdir(directory, 0o700)
        os.chown(directory, owner_uid, owner_gid, follow_symlinks=False)
        os.chmod(directory, 0o700, follow_symlinks=False)
        fsync_directory(state_root)
    except OSError as exc:
        raise TransactionError(
            "state_write_failed", "transaction generation could not be created"
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
                "current_missing", "current transaction ownership is missing"
            )
        return None
    document, _payload, _info = read_private_json(
        path,
        label="current transaction ownership",
        max_bytes=MAX_STATE_BYTES,
        owner_uid=owner_uid,
    )
    if set(document) != {"schema_version", "generation", "manifest_sha256"}:
        raise TransactionError("invalid_state", "current transaction state is invalid")
    if document["schema_version"] != CURRENT_SCHEMA:
        raise TransactionError("invalid_state", "current transaction state is invalid")
    generation = document["generation"]
    if not isinstance(generation, str) or not GENERATION_RE.fullmatch(generation):
        raise TransactionError("invalid_state", "current transaction state is invalid")
    validate_sha256(document["manifest_sha256"], "current manifest")
    return document


def install_current(
    state_root: Path,
    generation: str,
    manifest_payload: bytes,
    *,
    owner_uid: int,
    owner_gid: int,
) -> None:
    document = {
        "schema_version": CURRENT_SCHEMA,
        "generation": generation,
        "manifest_sha256": sha256_bytes(manifest_payload),
    }
    write_atomic_private(
        current_path(state_root),
        json_bytes(document),
        owner_uid=owner_uid,
        owner_gid=owner_gid,
    )


def release_current(state_root: Path, generation: str, *, owner_uid: int) -> None:
    current = load_current(state_root, owner_uid=owner_uid, required=False)
    if current is None:
        return
    if current["generation"] != generation:
        raise TransactionError(
            "stale_transaction", "transaction is not the current generation"
        )
    try:
        os.unlink(current_path(state_root))
        fsync_directory(state_root)
    except OSError as exc:
        raise TransactionError(
            "state_write_failed", "current transaction could not be released"
        ) from exc


def validate_file_provenance(value: Any, label: str) -> dict[str, Any]:
    expected_keys = {
        "path",
        "sha256",
        "uid",
        "gid",
        "mode",
        "size",
        "device",
        "inode",
        "mtime_ns",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise TransactionError("invalid_state", f"{label} provenance is invalid")
    result = {
        "path": str(absolute_path(value["path"], label)),
        "sha256": validate_sha256(value["sha256"], label),
    }
    for key in ("uid", "gid", "mode", "size", "device", "inode", "mtime_ns"):
        result[key] = validate_nonnegative_integer(value[key], f"{label} {key}")
    if result["mode"] > 0o7777:
        raise TransactionError("invalid_state", f"{label} provenance is invalid")
    return result


def validate_content_provenance(value: Any, label: str) -> dict[str, Any]:
    expected_keys = {"path", "sha256", "uid", "gid", "mode", "size"}
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise TransactionError("invalid_state", f"{label} provenance is invalid")
    result = {
        "path": str(absolute_path(value["path"], label)),
        "sha256": validate_sha256(value["sha256"], label),
    }
    for key in ("uid", "gid", "mode", "size"):
        result[key] = validate_nonnegative_integer(value[key], f"{label} {key}")
    if result["mode"] > 0o7777:
        raise TransactionError("invalid_state", f"{label} provenance is invalid")
    return result


def validate_stored_provenance(value: Any, service: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "host_fingerprint",
        "package",
        "collector_binary",
        "collector_config",
        "unit",
    }:
        raise TransactionError("invalid_state", "runtime provenance is invalid")
    host = validate_sha256(value["host_fingerprint"], "host fingerprint")
    package = value["package"]
    if not isinstance(package, dict) or set(package) != {"name", "version"}:
        raise TransactionError("invalid_state", "package provenance is invalid")
    if (
        package["name"] not in PACKAGE_ALLOWLIST
        or not isinstance(package["version"], str)
        or not SAFE_VERSION_RE.fullmatch(package["version"])
    ):
        raise TransactionError("invalid_state", "package provenance is invalid")
    collector = validate_file_provenance(value["collector_binary"], "collector binary")
    collector_config = validate_content_provenance(
        value["collector_config"], "collector config"
    )
    if (
        collector_config["path"] != str(COLLECTOR_CONFIG_PATH)
        or collector_config["uid"] != 0
        or collector_config["gid"] != 0
        or collector_config["mode"] != 0o644
        or collector_config["size"] > MAX_COLLECTOR_CONFIG_BYTES
    ):
        raise TransactionError(
            "invalid_state", "collector config provenance is invalid"
        )
    unit = value["unit"]
    if not isinstance(unit, dict) or set(unit) != {
        "name",
        "unit_file_state",
        "user",
        "group",
        "service_uid",
        "service_gid",
        "fragment",
        "unmanaged_dropins",
    }:
        raise TransactionError("invalid_state", "systemd provenance is invalid")
    if unit["name"] != service:
        raise TransactionError("invalid_state", "systemd provenance is invalid")
    if (
        not isinstance(unit["unit_file_state"], str)
        or not unit["unit_file_state"]
        or len(unit["unit_file_state"]) > 64
        or any(
            ord(character) < 0x20 or ord(character) == 0x7F
            for character in unit["unit_file_state"]
        )
    ):
        raise TransactionError("invalid_state", "systemd provenance is invalid")
    if (
        not isinstance(unit["user"], str)
        or not SAFE_IDENTITY_RE.fullmatch(unit["user"])
        or not isinstance(unit["group"], str)
        or not SAFE_IDENTITY_RE.fullmatch(unit["group"])
    ):
        raise TransactionError("invalid_state", "systemd provenance is invalid")
    service_uid = validate_nonnegative_integer(unit["service_uid"], "service uid")
    service_gid = validate_nonnegative_integer(unit["service_gid"], "service gid")
    fragment = validate_file_provenance(unit["fragment"], "systemd unit fragment")
    dropins_value = unit["unmanaged_dropins"]
    if dropins_value != []:
        raise TransactionError("invalid_state", "systemd provenance is invalid")
    dropins: list[dict[str, Any]] = []
    return {
        "host_fingerprint": host,
        "package": dict(package),
        "collector_binary": collector,
        "collector_config": collector_config,
        "unit": {
            "name": service,
            "unit_file_state": unit["unit_file_state"],
            "user": unit["user"],
            "group": unit["group"],
            "service_uid": service_uid,
            "service_gid": service_gid,
            "fragment": fragment,
            "unmanaged_dropins": dropins,
        },
    }


def validate_state_document(
    document: Any, manifest_path: Path, *, owner_uid: int
) -> dict[str, Any]:
    if not isinstance(document, dict) or set(document) != {
        "schema_version",
        "generation",
        "created_at",
        "state_root",
        "owner_uid",
        "request_sha256",
        "service",
        "provenance",
        "files",
    }:
        raise TransactionError("invalid_state", "transaction manifest is invalid")
    if document["schema_version"] != STATE_SCHEMA:
        raise TransactionError("invalid_state", "transaction manifest is invalid")
    generation = document["generation"]
    if not isinstance(generation, str) or not GENERATION_RE.fullmatch(generation):
        raise TransactionError("invalid_state", "transaction generation is invalid")
    state_root = absolute_path(document["state_root"], "state root")
    state_directory = state_root / f"generation-{generation}"
    if (
        manifest_path != state_directory / "manifest.json"
        or document["owner_uid"] != owner_uid
    ):
        raise TransactionError("invalid_state", "transaction manifest path is invalid")
    assert_private_directory(state_root, owner_uid=owner_uid, label="state root")
    assert_private_directory(
        state_directory, owner_uid=owner_uid, label="transaction generation"
    )
    validate_sha256(document["request_sha256"], "request")
    if not isinstance(document["created_at"], str) or len(document["created_at"]) > 64:
        raise TransactionError("invalid_state", "transaction timestamp is invalid")
    service_value = document["service"]
    if not isinstance(service_value, dict) or set(service_value) != {
        "name",
        "health_url",
        "health_timeout_seconds",
    }:
        raise TransactionError("invalid_state", "transaction service is invalid")
    service = {
        "name": validate_service_name(service_value["name"]),
        "health_url": validate_health_url(service_value["health_url"]),
        "health_timeout_seconds": validate_timeout(
            service_value["health_timeout_seconds"]
        ),
    }
    if service["name"] != COLLECTOR_SERVICE:
        raise TransactionError("invalid_state", "transaction service is invalid")
    provenance = validate_stored_provenance(document["provenance"], service["name"])
    files_value = document["files"]
    if not isinstance(files_value, list) or len(files_value) != len(ROLES):
        raise TransactionError("invalid_state", "transaction file inventory is invalid")
    files: list[dict[str, Any]] = []
    roles: set[str] = set()
    targets: set[str] = set()
    for index, value in enumerate(files_value):
        if not isinstance(value, dict) or set(value) != {
            "role",
            "action",
            "target",
            "desired",
            "original",
        }:
            raise TransactionError("invalid_state", "transaction file entry is invalid")
        role = value["role"]
        action = value["action"]
        if role not in ROLES or role in roles or action not in {"install", "remove"}:
            raise TransactionError("invalid_state", "transaction file entry is invalid")
        target = absolute_path(value["target"], "bundle target")
        validate_target_path(role, target, service["name"])
        if str(target) in targets:
            raise TransactionError("invalid_state", "transaction targets are invalid")
        desired = value["desired"]
        if action == "install":
            desired = state_metadata(desired, allow_size=ROLE_LIMITS[role])
        elif desired is not None:
            raise TransactionError("invalid_state", "remove desired state is invalid")
        original_value = value["original"]
        if not isinstance(original_value, dict) or not isinstance(
            original_value.get("existed"), bool
        ):
            raise TransactionError("invalid_state", "original file state is invalid")
        if original_value["existed"]:
            if set(original_value) != {
                "existed",
                "sha256",
                "uid",
                "gid",
                "mode",
                "size",
                "xattrs",
                "backup",
            }:
                raise TransactionError(
                    "invalid_state", "original file state is invalid"
                )
            backup = original_value["backup"]
            if backup != f"backup-{index}.bin":
                raise TransactionError("invalid_state", "backup identity is invalid")
            original = {
                "existed": True,
                **state_metadata(
                    {
                        key: original_value[key]
                        for key in ("sha256", "uid", "gid", "mode", "size", "xattrs")
                    },
                    allow_size=ROLE_LIMITS[role],
                ),
                "backup": backup,
            }
        else:
            if set(original_value) != {"existed"}:
                raise TransactionError(
                    "invalid_state", "original file state is invalid"
                )
            original = {"existed": False}
        roles.add(role)
        targets.add(str(target))
        files.append(
            {
                "role": role,
                "action": action,
                "target": str(target),
                "desired": desired,
                "original": original,
            }
        )
    if tuple(item["role"] for item in files) != ROLES:
        raise TransactionError("invalid_state", "transaction file order is invalid")
    return {
        "schema_version": STATE_SCHEMA,
        "generation": generation,
        "created_at": document["created_at"],
        "state_root": str(state_root),
        "owner_uid": owner_uid,
        "request_sha256": document["request_sha256"],
        "service": service,
        "provenance": provenance,
        "files": files,
    }


def load_state_manifest(path: Path, *, owner_uid: int) -> tuple[dict[str, Any], bytes]:
    document, payload, _info = read_private_json(
        path,
        label="transaction manifest",
        max_bytes=MAX_STATE_BYTES,
        owner_uid=owner_uid,
    )
    return validate_state_document(document, path, owner_uid=owner_uid), payload


def require_current_ownership(
    document: Mapping[str, Any], manifest_payload: bytes, *, owner_uid: int
) -> None:
    state_root = Path(document["state_root"])
    current = load_current(state_root, owner_uid=owner_uid, required=True)
    assert current is not None
    if current["generation"] != document["generation"] or not hmac.compare_digest(
        current["manifest_sha256"], sha256_bytes(manifest_payload)
    ):
        raise TransactionError(
            "stale_transaction", "transaction is not the current generation"
        )


def initial_journal(generation: str) -> dict[str, Any]:
    return {
        "schema_version": JOURNAL_SCHEMA,
        "generation": generation,
        "phase": "prepared",
        "apply_cursor": 0,
        "apply_service_cursor": 0,
        "restore_cursor": 0,
        "restore_service_cursor": 0,
        "intent": None,
        "updated_at": utc_now(),
    }


def validate_journal(value: Any, generation: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "generation",
        "phase",
        "apply_cursor",
        "apply_service_cursor",
        "restore_cursor",
        "restore_service_cursor",
        "intent",
        "updated_at",
    }:
        raise TransactionError("invalid_state", "transaction journal is invalid")
    if value["schema_version"] != JOURNAL_SCHEMA or value["generation"] != generation:
        raise TransactionError("invalid_state", "transaction journal is invalid")
    if value["phase"] not in {
        "prepared",
        "applying",
        "applied",
        "restoring",
        "recovery_required",
        "restored",
    }:
        raise TransactionError("invalid_state", "transaction journal phase is invalid")
    bounds = {
        "apply_cursor": len(APPLY_ORDER),
        "apply_service_cursor": 3,
        "restore_cursor": len(RESTORE_ORDER),
        "restore_service_cursor": 3,
    }
    for key, maximum in bounds.items():
        observed = value[key]
        if (
            isinstance(observed, bool)
            or not isinstance(observed, int)
            or not 0 <= observed <= maximum
        ):
            raise TransactionError(
                "invalid_state", "transaction journal cursor is invalid"
            )
    intent = value["intent"]
    if intent is not None:
        if not isinstance(intent, dict) or set(intent) != {"kind", "index"}:
            raise TransactionError(
                "invalid_state", "transaction journal intent is invalid"
            )
        if intent["kind"] not in {
            "apply_file",
            "apply_service",
            "restore_file",
            "restore_service",
        }:
            raise TransactionError(
                "invalid_state", "transaction journal intent is invalid"
            )
        if isinstance(intent["index"], bool) or not isinstance(intent["index"], int):
            raise TransactionError(
                "invalid_state", "transaction journal intent is invalid"
            )
    if not isinstance(value["updated_at"], str) or len(value["updated_at"]) > 64:
        raise TransactionError(
            "invalid_state", "transaction journal timestamp is invalid"
        )
    return dict(value)


def journal_path(document: Mapping[str, Any]) -> Path:
    return (
        Path(document["state_root"])
        / f"generation-{document['generation']}"
        / "journal.json"
    )


def load_journal(document: Mapping[str, Any], *, owner_uid: int) -> dict[str, Any]:
    value, _payload, _info = read_private_json(
        journal_path(document),
        label="transaction journal",
        max_bytes=MAX_STATE_BYTES,
        owner_uid=owner_uid,
    )
    return validate_journal(value, str(document["generation"]))


def after_checkpoint(_phase: str, _intent: Mapping[str, Any] | None) -> None:
    """Test seam after the journal and its directory are durable."""


def write_journal(
    document: Mapping[str, Any],
    journal: Mapping[str, Any],
    *,
    manifest_payload: bytes,
    owner_uid: int,
    owner_gid: int,
    invoke_hook: bool = True,
) -> dict[str, Any]:
    require_current_ownership(document, manifest_payload, owner_uid=owner_uid)
    updated = dict(journal)
    updated["updated_at"] = utc_now()
    validate_journal(updated, str(document["generation"]))
    write_atomic_private(
        journal_path(document),
        json_bytes(updated),
        owner_uid=owner_uid,
        owner_gid=owner_gid,
    )
    if invoke_hook:
        after_checkpoint(updated["phase"], updated["intent"])
    return updated


def checkpoint(
    document: Mapping[str, Any],
    journal: Mapping[str, Any],
    *,
    manifest_payload: bytes,
    owner_uid: int,
    owner_gid: int,
    **changes: Any,
) -> dict[str, Any]:
    updated = dict(journal)
    updated.update(changes)
    return write_journal(
        document,
        updated,
        manifest_payload=manifest_payload,
        owner_uid=owner_uid,
        owner_gid=owner_gid,
    )


def mark_recovery_required(
    document: Mapping[str, Any],
    manifest_payload: bytes,
    *,
    owner_uid: int,
    owner_gid: int,
) -> None:
    try:
        journal = load_journal(document, owner_uid=owner_uid)
        journal["phase"] = "recovery_required"
        write_journal(
            document,
            journal,
            manifest_payload=manifest_payload,
            owner_uid=owner_uid,
            owner_gid=owner_gid,
            invoke_hook=False,
        )
    except BaseException:
        pass


def validate_secret_payload(payload: bytes) -> None:
    try:
        lines = payload.decode("utf-8", errors="strict").splitlines()
    except UnicodeDecodeError as exc:
        raise TransactionError(
            "invalid_secret", "Galileo key staging file must contain UTF-8 text"
        ) from exc
    if (
        len(lines) != 1
        or not lines[0]
        or any(
            ord(character) < 0x20 or ord(character) == 0x7F for character in lines[0]
        )
    ):
        raise TransactionError(
            "invalid_secret", "Galileo key staging file must contain one nonempty line"
        )


def capture_sources(
    request: Mapping[str, Any], *, owner_uid: int
) -> dict[str, dict[str, Any]]:
    captured: dict[str, dict[str, Any]] = {}
    for role in APPLY_ORDER:
        entry = request["files"][role]
        if entry["action"] != "install":
            continue
        path = Path(entry["source"])
        state, payload, info = file_state(
            path,
            label="staged bundle source",
            max_bytes=ROLE_LIMITS[role],
            owner_uid=owner_uid,
        )
        if not payload:
            raise TransactionError("invalid_source", "staged bundle source is empty")
        if (
            not hmac.compare_digest(state["sha256"], entry["sha256"])
            or state["uid"] != entry["uid"]
            or state["gid"] != entry["gid"]
            or state["mode"] != entry["mode"]
        ):
            raise TransactionError(
                "source_mismatch", "staged source hash or metadata does not match"
            )
        if state["xattrs"]:
            raise TransactionError(
                "invalid_source_metadata",
                "staged bundle sources must not carry extended attributes",
            )
        if role == "galileo_key":
            validate_secret_payload(payload)
        captured[role] = {
            "path": path,
            "state": state,
            "payload": payload,
            "device": info.st_dev,
            "inode": info.st_ino,
            "mtime_ns": info.st_mtime_ns,
        }
    return captured


def recheck_source(role: str, captured: Mapping[str, Any], *, owner_uid: int) -> bytes:
    before_source_recheck(role)
    state, payload, info = file_state(
        captured["path"],
        label="staged bundle source",
        max_bytes=ROLE_LIMITS[role],
        owner_uid=owner_uid,
    )
    if (
        not states_equal(state, captured["state"])
        or info.st_dev != captured["device"]
        or info.st_ino != captured["inode"]
        or info.st_mtime_ns != captured["mtime_ns"]
    ):
        raise TransactionError("source_changed", "staged source changed during apply")
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
    role: str,
    path: Path,
    captured: Mapping[str, Any],
    *,
    owner_uid: int,
) -> None:
    if not optional_target_matches(
        path, captured["state"], role=role, owner_uid=owner_uid
    ):
        raise TransactionError(
            "target_changed", "bundle target changed during snapshot"
        )
    if captured["state"].get("existed"):
        _state, _payload, info = file_state(
            path,
            label="bundle target",
            max_bytes=ROLE_LIMITS[role],
            owner_uid=owner_uid,
        )
        if (
            info.st_dev != captured["device"]
            or info.st_ino != captured["inode"]
            or info.st_mtime_ns != captured["mtime_ns"]
        ):
            raise TransactionError(
                "target_changed", "bundle target changed during snapshot"
            )


def prepare_state(
    request: Mapping[str, Any],
    request_sha256: str,
    provenance: Mapping[str, Any],
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
        requested = request["files"][role]
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
        desired = sources[role]["state"] if requested["action"] == "install" else None
        files.append(
            {
                "role": role,
                "action": requested["action"],
                "target": requested["target"],
                "desired": desired,
                "original": original,
            }
        )
    document = {
        "schema_version": STATE_SCHEMA,
        "generation": generation,
        "created_at": utc_now(),
        "state_root": request["state_root"],
        "owner_uid": owner_uid,
        "request_sha256": request_sha256,
        "service": request["service"],
        "provenance": copy.deepcopy(provenance),
        "files": files,
    }
    manifest_path = state_dir / "manifest.json"
    normalized = validate_state_document(document, manifest_path, owner_uid=owner_uid)
    payload = json_bytes(normalized)
    write_exclusive(
        manifest_path,
        payload,
        mode=0o600,
        owner_uid=owner_uid,
        owner_gid=owner_gid,
    )
    journal = initial_journal(generation)
    write_exclusive(
        state_dir / "journal.json",
        json_bytes(journal),
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


SERVICE_STEPS = ("daemon_reload", "restart", "health")


def apply_files(
    document: Mapping[str, Any],
    manifest_payload: bytes,
    journal: dict[str, Any],
    sources: Mapping[str, Mapping[str, Any]],
    targets: Mapping[str, Mapping[str, Any]],
    system: Any,
    *,
    owner_uid: int,
    owner_gid: int,
) -> dict[str, Any]:
    managed_dropin = Path(document["files"][-1]["target"])
    by_role = {entry["role"]: entry for entry in document["files"]}
    for index, role in enumerate(APPLY_ORDER):
        if index < journal["apply_cursor"]:
            continue
        entry = by_role[role]
        journal = checkpoint(
            document,
            journal,
            manifest_payload=manifest_payload,
            owner_uid=owner_uid,
            owner_gid=owner_gid,
            phase="applying",
            intent={"kind": "apply_file", "index": index},
        )
        boundary = f"apply-file-{index}"
        verify_boundary(
            system,
            document["provenance"],
            managed_dropin=managed_dropin,
            boundary=f"before-{boundary}",
        )
        target = Path(entry["target"])
        if role == "galileo_key":
            validate_secret_directory(document["provenance"], root_uid=owner_uid)
        verify_original_target(role, target, targets[role], owner_uid=owner_uid)
        if entry["action"] == "install":
            payload = recheck_source(role, sources[role], owner_uid=owner_uid)
            atomic_install(
                target,
                payload,
                entry["desired"],
                expected_current=targets[role]["state"],
                role=role,
                owner_uid=owner_uid,
            )
            verify_installed(
                target,
                entry["desired"],
                role=role,
                owner_uid=owner_uid,
            )
        else:
            atomic_remove(
                target,
                expected_current=targets[role]["state"],
                role=role,
                owner_uid=owner_uid,
            )
            if not optional_target_matches(
                target, {"existed": False}, role=role, owner_uid=owner_uid
            ):
                raise TransactionError(
                    "remove_verification_failed",
                    "bundle target removal was not durable",
                )
        verify_boundary(
            system,
            document["provenance"],
            managed_dropin=managed_dropin,
            boundary=f"after-{boundary}",
        )
        journal = checkpoint(
            document,
            journal,
            manifest_payload=manifest_payload,
            owner_uid=owner_uid,
            owner_gid=owner_gid,
            apply_cursor=index + 1,
            intent=None,
        )
    return journal


def run_service_steps(
    document: Mapping[str, Any],
    manifest_payload: bytes,
    journal: dict[str, Any],
    system: Any,
    *,
    restoring: bool,
    owner_uid: int,
    owner_gid: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    managed_dropin = Path(document["files"][-1]["target"])
    by_role = {entry["role"]: entry for entry in document["files"]}
    wrapper = Path(by_role["runtime_wrapper"]["target"])
    enforcing_runtime = by_role["collector_dropin"]["action"] == "install"
    cursor_name = "restore_service_cursor" if restoring else "apply_service_cursor"
    intent_kind = "restore_service" if restoring else "apply_service"
    prefix = "restore" if restoring else "apply"
    health: dict[str, Any] = {"checked": False, "ok": True}
    for index, step in enumerate(SERVICE_STEPS):
        if index < journal[cursor_name]:
            continue
        journal = checkpoint(
            document,
            journal,
            manifest_payload=manifest_payload,
            owner_uid=owner_uid,
            owner_gid=owner_gid,
            phase="restoring" if restoring else "applying",
            intent={"kind": intent_kind, "index": index},
        )
        boundary = f"{prefix}-service-{index}"
        verify_boundary(
            system,
            document["provenance"],
            managed_dropin=managed_dropin,
            boundary=f"before-{boundary}",
        )
        if step == "daemon_reload":
            system.daemon_reload(document["service"]["name"])
        elif step == "restart":
            system.restart(document["service"]["name"])
        else:
            health = system.health(
                document["service"]["health_url"],
                document["service"]["health_timeout_seconds"],
            )
        if not restoring and enforcing_runtime:
            system.verify_runtime_contract(
                service=document["service"]["name"],
                managed_dropin=managed_dropin,
                wrapper=wrapper,
            )
        verify_boundary(
            system,
            document["provenance"],
            managed_dropin=managed_dropin,
            boundary=f"after-{boundary}",
        )
        journal = checkpoint(
            document,
            journal,
            manifest_payload=manifest_payload,
            owner_uid=owner_uid,
            owner_gid=owner_gid,
            **{cursor_name: index + 1, "intent": None},
        )
    return journal, health


def load_backup(
    document: Mapping[str, Any], entry: Mapping[str, Any], *, owner_uid: int
) -> bytes:
    original = entry["original"]
    if not original["existed"]:
        raise TransactionError("invalid_state", "absent file has no backup")
    state_dir = Path(document["state_root"]) / f"generation-{document['generation']}"
    backup_path = state_dir / original["backup"]
    payload, info = read_regular_file(
        backup_path,
        label="transaction backup",
        max_bytes=ROLE_LIMITS[entry["role"]],
        owner_uid=owner_uid,
    )
    if info.st_uid != owner_uid or stat.S_IMODE(info.st_mode) != 0o600:
        raise TransactionError(
            "unsafe_backup", "transaction backup is not owner-only mode 0600"
        )
    if len(payload) != original["size"] or not hmac.compare_digest(
        sha256_bytes(payload), original["sha256"]
    ):
        raise TransactionError(
            "backup_hash_mismatch", "transaction backup does not match its snapshot"
        )
    return payload


def desired_optional_state(entry: Mapping[str, Any]) -> dict[str, Any]:
    if entry["action"] == "remove":
        return {"existed": False}
    return {"existed": True, **entry["desired"]}


def restore_one_file(
    document: Mapping[str, Any], entry: Mapping[str, Any], *, owner_uid: int
) -> None:
    role = entry["role"]
    if role == "galileo_key":
        validate_secret_directory(document["provenance"], root_uid=owner_uid)
    target = Path(entry["target"])
    original = entry["original"]
    desired = desired_optional_state(entry)
    is_original = optional_target_matches(
        target, original, role=role, owner_uid=owner_uid
    )
    is_desired = optional_target_matches(
        target, desired, role=role, owner_uid=owner_uid
    )
    if not is_original and not is_desired:
        raise TransactionError(
            "target_drift", "bundle target matches neither transaction generation"
        )
    if not is_original:
        if original["existed"]:
            payload = load_backup(document, entry, owner_uid=owner_uid)
            atomic_install(
                target,
                payload,
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
            "restore_verification_failed", "bundle target was not exactly restored"
        )


def restore_from_document(
    document: Mapping[str, Any],
    manifest_payload: bytes,
    system: Any,
    *,
    owner_uid: int,
    owner_gid: int,
) -> dict[str, Any]:
    require_current_ownership(document, manifest_payload, owner_uid=owner_uid)
    validate_secret_directory(document["provenance"], root_uid=owner_uid)
    journal = load_journal(document, owner_uid=owner_uid)
    if journal["phase"] == "restored":
        release_current(
            Path(document["state_root"]),
            str(document["generation"]),
            owner_uid=owner_uid,
        )
        return {"status": "restored", "health": {"checked": False, "ok": True}}
    journal = checkpoint(
        document,
        journal,
        manifest_payload=manifest_payload,
        owner_uid=owner_uid,
        owner_gid=owner_gid,
        phase="restoring",
        intent=None,
    )
    managed_dropin = Path(document["files"][-1]["target"])
    by_role = {entry["role"]: entry for entry in document["files"]}
    for index, role in enumerate(RESTORE_ORDER):
        if index < journal["restore_cursor"]:
            continue
        journal = checkpoint(
            document,
            journal,
            manifest_payload=manifest_payload,
            owner_uid=owner_uid,
            owner_gid=owner_gid,
            phase="restoring",
            intent={"kind": "restore_file", "index": index},
        )
        boundary = f"restore-file-{index}"
        verify_boundary(
            system,
            document["provenance"],
            managed_dropin=managed_dropin,
            boundary=f"before-{boundary}",
        )
        restore_one_file(document, by_role[role], owner_uid=owner_uid)
        verify_boundary(
            system,
            document["provenance"],
            managed_dropin=managed_dropin,
            boundary=f"after-{boundary}",
        )
        journal = checkpoint(
            document,
            journal,
            manifest_payload=manifest_payload,
            owner_uid=owner_uid,
            owner_gid=owner_gid,
            restore_cursor=index + 1,
            intent=None,
        )
    journal, health = run_service_steps(
        document,
        manifest_payload,
        journal,
        system,
        restoring=True,
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
                "restore_verification_failed", "runtime bundle restore is incomplete"
            )
    verify_boundary(
        system,
        document["provenance"],
        managed_dropin=managed_dropin,
        boundary="before-restored",
    )
    checkpoint(
        document,
        journal,
        manifest_payload=manifest_payload,
        owner_uid=owner_uid,
        owner_gid=owner_gid,
        phase="restored",
        intent=None,
    )
    release_current(
        Path(document["state_root"]),
        str(document["generation"]),
        owner_uid=owner_uid,
    )
    return {"status": "restored", "health": health}


def _as_transaction_error(error: BaseException) -> TransactionError:
    if isinstance(error, TransactionError):
        return error
    if isinstance(error, (KeyboardInterrupt, SystemExit)):
        return TransactionError(
            "interrupted", "runtime-bundle transaction was interrupted"
        )
    return TransactionError("apply_failed", "runtime-bundle apply failed")


def apply_bundle(
    request_path: Path,
    *,
    system: Any | None = None,
    owner_uid: int = 0,
    owner_gid: int = 0,
) -> dict[str, Any]:
    request_path = absolute_path(str(request_path), "bundle request")
    first_raw, first_payload, first_info = read_private_json(
        request_path,
        label="bundle request",
        max_bytes=MAX_REQUEST_BYTES,
        owner_uid=owner_uid,
    )
    request = parse_request(first_raw)
    state_root = Path(request["state_root"])
    all_paths = {
        Path(entry[key])
        for entry in request["files"].values()
        for key in ("source", "target")
        if key in entry
    }
    if (
        request_path in all_paths
        or state_root == request_path
        or state_root in request_path.parents
        or request_path in state_root.parents
    ):
        raise TransactionError(
            "invalid_manifest", "request path overlaps transaction data"
        )
    ensure_state_root(state_root, owner_uid=owner_uid)
    with acquire_lock(state_root, owner_uid=owner_uid, owner_gid=owner_gid):
        if load_current(state_root, owner_uid=owner_uid, required=False) is not None:
            raise TransactionError(
                "current_generation",
                "restore the current runtime-bundle generation before another apply",
            )
        second_raw, second_payload, second_info = read_private_json(
            request_path,
            label="bundle request",
            max_bytes=MAX_REQUEST_BYTES,
            owner_uid=owner_uid,
        )
        if (
            first_raw != second_raw
            or not hmac.compare_digest(first_payload, second_payload)
            or (
                first_info.st_dev,
                first_info.st_ino,
                first_info.st_size,
                first_info.st_mtime_ns,
            )
            != (
                second_info.st_dev,
                second_info.st_ino,
                second_info.st_size,
                second_info.st_mtime_ns,
            )
        ):
            raise TransactionError(
                "request_changed", "bundle request changed while locking"
            )
        managed_dropin = Path(request["files"]["collector_dropin"]["target"])
        active_system = system or RuntimeSystem(owner_uid=owner_uid)
        provenance = active_system.capture(request, managed_dropin=managed_dropin)
        validate_role_metadata(
            request,
            provenance,
            root_uid=owner_uid,
            root_gid=owner_gid,
        )
        validate_secret_directory(provenance, root_uid=owner_uid)
        sources = capture_sources(request, owner_uid=owner_uid)
        validate_routing_environment_contract(request, sources)
        validate_dropin_contract(request, sources)
        targets = capture_targets(request, owner_uid=owner_uid)
        generation = secrets.token_hex(16)
        state_dir = create_state_directory(
            state_root,
            generation,
            owner_uid=owner_uid,
            owner_gid=owner_gid,
        )
        document, manifest_payload = prepare_state(
            request,
            sha256_bytes(first_payload),
            provenance,
            sources,
            targets,
            state_dir,
            generation,
            owner_uid=owner_uid,
            owner_gid=owner_gid,
        )
        health: dict[str, Any] = {"checked": False, "ok": True}
        try:
            after_checkpoint("prepared", None)
            journal = load_journal(document, owner_uid=owner_uid)
            journal = apply_files(
                document,
                manifest_payload,
                journal,
                sources,
                targets,
                active_system,
                owner_uid=owner_uid,
                owner_gid=owner_gid,
            )
            journal, health = run_service_steps(
                document,
                manifest_payload,
                journal,
                active_system,
                restoring=False,
                owner_uid=owner_uid,
                owner_gid=owner_gid,
            )
            for entry in document["files"]:
                if not optional_target_matches(
                    Path(entry["target"]),
                    desired_optional_state(entry),
                    role=entry["role"],
                    owner_uid=owner_uid,
                ):
                    raise TransactionError(
                        "install_verification_failed",
                        "runtime bundle installation is incomplete",
                    )
            runtime_wrapper = next(
                Path(entry["target"])
                for entry in document["files"]
                if entry["role"] == "runtime_wrapper"
            )
            if (
                next(
                    entry["action"]
                    for entry in document["files"]
                    if entry["role"] == "collector_dropin"
                )
                == "install"
            ):
                active_system.verify_runtime_contract(
                    service=document["service"]["name"],
                    managed_dropin=managed_dropin,
                    wrapper=runtime_wrapper,
                )
            verify_boundary(
                active_system,
                document["provenance"],
                managed_dropin=managed_dropin,
                boundary="before-applied",
            )
            checkpoint(
                document,
                journal,
                manifest_payload=manifest_payload,
                owner_uid=owner_uid,
                owner_gid=owner_gid,
                phase="applied",
                intent=None,
            )
        except BaseException as original:
            rollback: dict[str, Any]
            try:
                restored = restore_from_document(
                    document,
                    manifest_payload,
                    active_system,
                    owner_uid=owner_uid,
                    owner_gid=owner_gid,
                )
                rollback = {"attempted": True, "ok": True, "health": restored["health"]}
            except BaseException:
                mark_recovery_required(
                    document,
                    manifest_payload,
                    owner_uid=owner_uid,
                    owner_gid=owner_gid,
                )
                rollback = {
                    "attempted": True,
                    "ok": False,
                    "recovery_required": True,
                }
            error = _as_transaction_error(original)
            error.generation = generation  # type: ignore[attr-defined]
            error.rollback = rollback  # type: ignore[attr-defined]
            raise error from original
        return {
            "ok": True,
            "operation": "apply",
            "status": "applied",
            "generation": generation,
            "file_count": len(ROLES),
            "service": {"restarted": True},
            "health": health,
        }


def restore_bundle(
    manifest_path: Path,
    *,
    system: Any | None = None,
    owner_uid: int = 0,
    owner_gid: int = 0,
) -> dict[str, Any]:
    manifest_path = absolute_path(str(manifest_path), "transaction manifest")
    first_document, first_payload = load_state_manifest(
        manifest_path, owner_uid=owner_uid
    )
    state_root = Path(first_document["state_root"])
    assert_private_directory(state_root, owner_uid=owner_uid, label="state root")
    with acquire_lock(state_root, owner_uid=owner_uid, owner_gid=owner_gid):
        document, manifest_payload = load_state_manifest(
            manifest_path, owner_uid=owner_uid
        )
        if first_document != document or not hmac.compare_digest(
            first_payload, manifest_payload
        ):
            raise TransactionError(
                "manifest_changed", "transaction manifest changed while locking"
            )
        current = load_current(state_root, owner_uid=owner_uid, required=False)
        journal = load_journal(document, owner_uid=owner_uid)
        if current is None and journal["phase"] == "restored":
            return {
                "ok": True,
                "operation": "restore",
                "status": "restored",
                "generation": document["generation"],
                "health": {"checked": False, "ok": True},
            }
        require_current_ownership(document, manifest_payload, owner_uid=owner_uid)
        active_system = system or RuntimeSystem(owner_uid=owner_uid)
        try:
            restored = restore_from_document(
                document,
                manifest_payload,
                active_system,
                owner_uid=owner_uid,
                owner_gid=owner_gid,
            )
        except BaseException as original:
            mark_recovery_required(
                document,
                manifest_payload,
                owner_uid=owner_uid,
                owner_gid=owner_gid,
            )
            error = _as_transaction_error(original)
            error.generation = document["generation"]  # type: ignore[attr-defined]
            error.rollback = {  # type: ignore[attr-defined]
                "attempted": True,
                "ok": False,
                "recovery_required": True,
            }
            raise error from original
        return {
            "ok": True,
            "operation": "restore",
            "status": restored["status"],
            "generation": document["generation"],
            "health": restored["health"],
        }


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(description=__doc__, allow_abbrev=False)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    apply_parser = subparsers.add_parser("apply", allow_abbrev=False)
    apply_parser.add_argument("--request", required=True, type=Path)
    restore_parser = subparsers.add_parser("restore", allow_abbrev=False)
    restore_parser.add_argument("--manifest", required=True, type=Path)
    return parser


def transaction_signal_handler(_signum: int, _frame: Any) -> None:
    raise TransactionError("interrupted", "runtime-bundle transaction was interrupted")


def install_signal_handlers() -> dict[int, Any]:
    previous: dict[int, Any] = {}
    try:
        for signal_number in (signal.SIGINT, signal.SIGTERM):
            previous[signal_number] = signal.getsignal(signal_number)
            signal.signal(signal_number, transaction_signal_handler)
    except (OSError, ValueError) as exc:
        for signal_number, handler in previous.items():
            signal.signal(signal_number, handler)
        raise TransactionError(
            "signal_handler_failed",
            "transaction signal handlers could not be installed",
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
            apply_bundle(args.request)
            if operation == "apply"
            else restore_bundle(args.manifest)
        )
        emit(result)
        return 0
    except TransactionError as exc:
        result: dict[str, Any] = {
            "ok": False,
            "operation": operation,
            "error": {"code": exc.code, "message": exc.safe_message},
        }
        generation = getattr(exc, "generation", None)
        rollback = getattr(exc, "rollback", None)
        if generation is not None:
            result["generation"] = generation
        if rollback is not None:
            result["rollback"] = rollback
        emit(result, stream=sys.stderr)
        return 1
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
