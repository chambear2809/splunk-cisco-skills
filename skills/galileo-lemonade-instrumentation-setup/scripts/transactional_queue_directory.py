#!/usr/bin/env python3
"""Create and safely retire one destination-bound Galileo Collector queue."""

from __future__ import annotations

import argparse
import datetime as dt
import errno
import fcntl
import grp
import hashlib
import hmac
import json
import os
import pwd
import re
import secrets
import signal
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, BinaryIO, Mapping, Sequence


STATE_SCHEMA = "galileo-queue-transaction-state/v1"
JOURNAL_SCHEMA = "galileo-queue-transaction-journal/v1"
CURRENT_SCHEMA = "galileo-queue-transaction-current/v1"

QUEUE_ROOT = Path("/var/lib/splunk-otel-collector/galileo-queue")
QUARANTINE_ROOT = Path("/var/lib/splunk-otel-collector/galileo-queue-quarantine")
STATE_ROOT = Path("/var/lib/galileo-queue-transactions")
PACKAGE_NAME = "splunk-otel-collector"
MACHINE_ID_PATHS = (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id"))
SYSTEMCTL_PATHS = ("/usr/bin/systemctl", "/bin/systemctl")
DPKG_QUERY = "/usr/bin/dpkg-query"

MAX_STATE_BYTES = 1024 * 1024
MAX_UNIT_BYTES = 8 * 1024 * 1024
MAX_COMMAND_OUTPUT = 32 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GENERATION_RE = re.compile(r"^[0-9a-f]{32}$")
SERVICE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@:-]{0,254}$")
VERSION_RE = re.compile(r"^[A-Za-z0-9.+:~_-]{1,256}$")
IDENTITY_RE = re.compile(r"^[A-Za-z0-9_.@-]{0,255}$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

SUBPROCESS_ENV = {
    "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG": "C",
    "LC_ALL": "C",
}


class TransactionError(RuntimeError):
    """An operational failure whose text is safe for machine output."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message


class JsonArgumentParser(argparse.ArgumentParser):
    """Keep rejected argv values out of diagnostics."""

    def error(self, _message: str) -> None:
        raise TransactionError("invalid_arguments", "command arguments are invalid")


def emit(document: Mapping[str, Any], *, stream: Any = sys.stdout) -> None:
    stream.write(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")
    stream.flush()


def utc_now() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def json_bytes(document: Mapping[str, Any]) -> bytes:
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def validate_runtime() -> None:
    if not sys.platform.startswith("linux"):
        raise TransactionError(
            "unsupported_platform", "queue transactions require Linux"
        )
    if os.geteuid() != 0:
        raise TransactionError("root_required", "queue transactions require root")


def validate_service(value: Any) -> str:
    if not isinstance(value, str) or not SERVICE_RE.fullmatch(value):
        raise TransactionError("invalid_service", "systemd service name is invalid")
    return value


def validate_version(value: Any) -> str:
    if not isinstance(value, str) or not VERSION_RE.fullmatch(value):
        raise TransactionError(
            "invalid_version", "collector package version is invalid"
        )
    return value


def validate_fingerprint(value: Any) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise TransactionError(
            "invalid_fingerprint",
            "destination fingerprint must be a lowercase SHA-256 digest",
        )
    return value


def absolute_path(value: Any, label: str) -> Path:
    if (
        not isinstance(value, str)
        or not value
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        raise TransactionError("invalid_path", f"{label} path is invalid")
    path = Path(value)
    if not path.is_absolute() or str(Path(os.path.normpath(path))) != str(path):
        raise TransactionError("invalid_path", f"{label} path must be canonical")
    return path


def path_components(path: Path) -> list[Path]:
    components: list[Path] = []
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        components.append(current)
    return components


def assert_trusted_path(
    path: Path,
    *,
    label: str,
    owner_uid: int,
    include_final: bool,
    allow_missing_final: bool = False,
) -> None:
    components = [Path(path.anchor), *path_components(path)]
    last = len(components) - 1
    for index, component in enumerate(components):
        if index == last and not include_final:
            break
        try:
            info = os.lstat(component)
        except FileNotFoundError as exc:
            if allow_missing_final and index == last:
                return
            raise TransactionError(
                "unsafe_path", f"{label} path is unavailable"
            ) from exc
        except OSError as exc:
            raise TransactionError(
                "unsafe_path", f"{label} path cannot be inspected"
            ) from exc
        if stat.S_ISLNK(info.st_mode):
            raise TransactionError("unsafe_path", f"{label} path contains a link")
        if index < last and not stat.S_ISDIR(info.st_mode):
            raise TransactionError(
                "unsafe_path", f"{label} ancestor is not a directory"
            )
        if info.st_uid not in {0, owner_uid} or stat.S_IMODE(info.st_mode) & 0o022:
            raise TransactionError(
                "unsafe_path",
                f"{label} ancestors must be trusted and not writable by group/other",
            )


def directory_identity(path: Path) -> dict[str, int]:
    info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise TransactionError(
            "unsafe_directory", "queue support path is not a directory"
        )
    return {
        "device": info.st_dev,
        "inode": info.st_ino,
        "uid": info.st_uid,
        "gid": info.st_gid,
        "mode": stat.S_IMODE(info.st_mode),
    }


def validate_support_roots(*, owner_uid: int) -> tuple[dict[str, int], dict[str, int]]:
    for path, label in (
        (QUEUE_ROOT, "queue root"),
        (QUARANTINE_ROOT, "quarantine root"),
    ):
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise TransactionError(
                "unsafe_directory", f"{label} cannot be resolved safely"
            ) from exc
        if str(resolved) != str(path):
            raise TransactionError("unsafe_directory", f"{label} must be canonical")
        assert_trusted_path(path, label=label, owner_uid=owner_uid, include_final=True)
    queue = directory_identity(QUEUE_ROOT)
    quarantine = directory_identity(QUARANTINE_ROOT)
    if queue["uid"] != owner_uid or queue["mode"] & 0o022:
        raise TransactionError(
            "unsafe_directory", "queue root must be owner-controlled and protected"
        )
    if quarantine["uid"] != owner_uid or quarantine["mode"] != 0o700:
        raise TransactionError(
            "unsafe_directory", "quarantine root must be owner-only mode 0700"
        )
    if queue["device"] != quarantine["device"]:
        raise TransactionError(
            "unsafe_directory", "queue and quarantine roots must share one filesystem"
        )
    return queue, quarantine


def require_service_traversal(
    path: Path, *, service_uid: int, service_gid: int
) -> None:
    for component in [Path(path.anchor), *path_components(path)]:
        try:
            info = os.lstat(component)
        except OSError as exc:
            raise TransactionError(
                "provenance_failed", "queue ancestry cannot be inspected"
            ) from exc
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise TransactionError(
                "provenance_failed", "queue ancestry is not a directory"
            )
        mode = stat.S_IMODE(info.st_mode)
        execute_bit = (
            0o100
            if info.st_uid == service_uid
            else 0o010
            if info.st_gid == service_gid
            else 0o001
        )
        if not mode & execute_bit:
            raise TransactionError(
                "provenance_failed", "collector cannot traverse queue ancestry"
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


def write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("short write")
        view = view[written:]


def write_exclusive(
    path: Path,
    payload: bytes,
    *,
    mode: int,
    owner_uid: int,
    owner_gid: int,
) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, mode)
        try:
            os.fchown(descriptor, owner_uid, owner_gid)
            os.fchmod(descriptor, mode)
            write_all(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        fsync_directory(path.parent)
    except OSError as exc:
        raise TransactionError(
            "state_write_failed", "transaction state could not be created"
        ) from exc


def write_atomic_private(
    path: Path,
    payload: bytes,
    *,
    owner_uid: int,
    owner_gid: int,
) -> None:
    assert_private_directory(path.parent, owner_uid=owner_uid, label="state directory")
    if path.exists():
        info = os.lstat(path)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != owner_uid
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise TransactionError("unsafe_state", "transaction state file is unsafe")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchown(descriptor, owner_uid, owner_gid)
        os.fchmod(descriptor, 0o600)
        write_all(descriptor, payload)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path)
        fsync_directory(path.parent)
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


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


def ensure_state_root(*, owner_uid: int, owner_gid: int) -> None:
    if STATE_ROOT.exists():
        assert_private_directory(STATE_ROOT, owner_uid=owner_uid, label="state root")
        return
    assert_trusted_path(
        STATE_ROOT,
        label="state root",
        owner_uid=owner_uid,
        include_final=False,
    )
    try:
        os.mkdir(STATE_ROOT, 0o700)
        os.chown(STATE_ROOT, owner_uid, owner_gid, follow_symlinks=False)
        os.chmod(STATE_ROOT, 0o700, follow_symlinks=False)
        fsync_directory(STATE_ROOT.parent)
    except OSError as exc:
        raise TransactionError(
            "state_write_failed", "state root could not be created"
        ) from exc
    assert_private_directory(STATE_ROOT, owner_uid=owner_uid, label="state root")


def safe_read_with_identity(
    path: Path, *, label: str, max_bytes: int, owner_uid: int
) -> tuple[bytes, os.stat_result]:
    assert_trusted_path(path, label=label, owner_uid=owner_uid, include_final=False)
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise TransactionError(
            "unsafe_state", f"{label} cannot be opened safely"
        ) from exc
    try:
        before = os.fstat(descriptor)
        named = os.lstat(path)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_dev != named.st_dev
            or before.st_ino != named.st_ino
            or before.st_size < 1
            or before.st_size > max_bytes
        ):
            raise TransactionError(
                "unsafe_state", f"{label} is not a bounded regular file"
            )
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
        named_after = os.lstat(path)
        if (
            len(payload) != before.st_size
            or (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            )
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            or (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            )
            != (
                named_after.st_dev,
                named_after.st_ino,
                named_after.st_size,
                named_after.st_mtime_ns,
            )
        ):
            raise TransactionError("unsafe_state", f"{label} changed while being read")
        return payload, after
    finally:
        os.close(descriptor)


def safe_read(path: Path, *, label: str, max_bytes: int, owner_uid: int) -> bytes:
    payload, _info = safe_read_with_identity(
        path, label=label, max_bytes=max_bytes, owner_uid=owner_uid
    )
    return payload


def read_private_json(
    path: Path, *, label: str, owner_uid: int
) -> tuple[dict[str, Any], bytes]:
    payload, info = safe_read_with_identity(
        path, label=label, max_bytes=MAX_STATE_BYTES, owner_uid=owner_uid
    )
    if info.st_uid != owner_uid or stat.S_IMODE(info.st_mode) != 0o600:
        raise TransactionError("unsafe_state", f"{label} must be owner-only mode 0600")
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise TransactionError("invalid_state", f"{label} is invalid JSON") from exc
    if not isinstance(document, dict):
        raise TransactionError("invalid_state", f"{label} must be a JSON object")
    return document, payload


def run_command(arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            list(arguments),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            env=SUBPROCESS_ENV,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise TransactionError(
            "provenance_failed", "local provenance command failed"
        ) from exc
    if (
        len(result.stdout) > MAX_COMMAND_OUTPUT
        or len(result.stderr) > MAX_COMMAND_OUTPUT
    ):
        raise TransactionError(
            "provenance_failed", "local provenance output is excessive"
        )
    return result


def systemctl_path() -> str:
    for candidate in SYSTEMCTL_PATHS:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    raise TransactionError("provenance_failed", "systemctl is unavailable")


def machine_fingerprint(*, owner_uid: int) -> str:
    for path in MACHINE_ID_PATHS:
        try:
            payload, info = safe_read_with_identity(
                path, label="machine identity", max_bytes=4096, owner_uid=owner_uid
            )
        except TransactionError:
            continue
        if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
            continue
        value = payload.strip()
        if value:
            return sha256_bytes(b"galileo-queue-host-v1\0" + value)
    raise TransactionError("provenance_failed", "machine identity is unavailable")


def package_version() -> str:
    result = run_command((DPKG_QUERY, "-W", "-f=${Version}", PACKAGE_NAME))
    value = result.stdout.strip()
    if result.returncode != 0 or not VERSION_RE.fullmatch(value):
        raise TransactionError(
            "provenance_failed", "collector package version is unavailable"
        )
    return value


def hashed_unit_file(path: Path, *, owner_uid: int) -> dict[str, Any]:
    payload, info = safe_read_with_identity(
        path, label="systemd unit file", max_bytes=MAX_UNIT_BYTES, owner_uid=owner_uid
    )
    mode = stat.S_IMODE(info.st_mode)
    if info.st_uid != 0 or mode & 0o022:
        raise TransactionError(
            "provenance_failed", "systemd unit file is not protected"
        )
    return {
        "path": str(path),
        "device": info.st_dev,
        "inode": info.st_ino,
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "uid": info.st_uid,
        "gid": info.st_gid,
        "mode": mode,
        "sha256": sha256_bytes(payload),
    }


def resolve_service_identity(user: str, group: str) -> tuple[int, int]:
    if not IDENTITY_RE.fullmatch(user) or not IDENTITY_RE.fullmatch(group):
        raise TransactionError(
            "provenance_failed", "collector service identity is invalid"
        )
    try:
        if user:
            user_record = pwd.getpwnam(user)
            uid = user_record.pw_uid
            primary_gid = user_record.pw_gid
        else:
            uid = 0
            primary_gid = 0
        gid = grp.getgrnam(group).gr_gid if group else primary_gid
    except KeyError as exc:
        raise TransactionError(
            "provenance_failed", "collector service identity is unavailable"
        ) from exc
    return uid, gid


def service_provenance(service: str, *, owner_uid: int) -> dict[str, Any]:
    names = "Id,LoadState,ActiveState,UnitFileState,User,Group,FragmentPath,DropInPaths"
    result = run_command(
        (systemctl_path(), "show", f"--property={names}", "--", service)
    )
    if result.returncode != 0:
        raise TransactionError(
            "provenance_failed", "collector service metadata is unavailable"
        )
    expected = set(names.split(","))
    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        if not separator or key not in expected or key in values:
            raise TransactionError(
                "provenance_failed", "collector service metadata is invalid"
            )
        if len(value) > 8192 or any(
            ord(character) < 0x20 or ord(character) == 0x7F for character in value
        ):
            raise TransactionError(
                "provenance_failed", "collector service metadata is invalid"
            )
        values[key] = value
    if set(values) != expected:
        raise TransactionError(
            "provenance_failed", "collector service metadata is incomplete"
        )
    if (
        values["Id"] != service
        or values["LoadState"] != "loaded"
        or values["ActiveState"] != "active"
        or values["UnitFileState"] not in {"enabled", "disabled"}
    ):
        raise TransactionError(
            "provenance_failed", "collector service state is unsupported"
        )
    uid, gid = resolve_service_identity(values["User"], values["Group"])
    paths = [absolute_path(values["FragmentPath"], "systemd unit fragment")]
    raw_dropins = values["DropInPaths"].split() if values["DropInPaths"] else []
    if len(raw_dropins) > 128 or len(raw_dropins) != len(set(raw_dropins)):
        raise TransactionError(
            "provenance_failed", "collector drop-in inventory is invalid"
        )
    paths.extend(
        absolute_path(value, "systemd drop-in") for value in sorted(raw_dropins)
    )
    records = [hashed_unit_file(path, owner_uid=owner_uid) for path in paths]
    # Runtime-bundle restore uses atomic replacement, so inode and mtime are
    # expected to change even when it restores exact bytes and metadata. Bind
    # the queue transaction to the stable unit/drop-in inventory and content.
    stable_records = [
        {key: record[key] for key in ("path", "size", "uid", "gid", "mode", "sha256")}
        for record in records
    ]
    unit_fingerprint = sha256_bytes(json_bytes({"files": stable_records, "version": 1}))
    return {
        "name": service,
        "user": values["User"],
        "group": values["Group"],
        "uid": uid,
        "gid": gid,
        "active_state": values["ActiveState"],
        "unit_file_state": values["UnitFileState"],
        "unit_fingerprint": unit_fingerprint,
    }


def validate_directory_identity(value: Any, label: str) -> dict[str, int]:
    keys = {"device", "inode", "uid", "gid", "mode"}
    if not isinstance(value, dict) or set(value) != keys:
        raise TransactionError("invalid_state", f"{label} identity is invalid")
    normalized: dict[str, int] = {}
    for key in keys:
        item = value[key]
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise TransactionError("invalid_state", f"{label} identity is invalid")
        normalized[key] = item
    if normalized["mode"] > 0o7777:
        raise TransactionError("invalid_state", f"{label} identity is invalid")
    return normalized


def validate_provenance(value: Any, service: str) -> dict[str, Any]:
    keys = {
        "machine_fingerprint",
        "package",
        "service",
        "queue_root",
        "quarantine_root",
    }
    if not isinstance(value, dict) or set(value) != keys:
        raise TransactionError("invalid_state", "queue provenance is invalid")
    machine = value["machine_fingerprint"]
    if not isinstance(machine, str) or not SHA256_RE.fullmatch(machine):
        raise TransactionError("invalid_state", "queue provenance is invalid")
    package = value["package"]
    if (
        not isinstance(package, dict)
        or set(package) != {"name", "version"}
        or package.get("name") != PACKAGE_NAME
    ):
        raise TransactionError("invalid_state", "queue provenance is invalid")
    version = validate_version(package.get("version"))
    unit = value["service"]
    unit_keys = {
        "name",
        "user",
        "group",
        "uid",
        "gid",
        "active_state",
        "unit_file_state",
        "unit_fingerprint",
    }
    if (
        not isinstance(unit, dict)
        or set(unit) != unit_keys
        or unit.get("name") != service
    ):
        raise TransactionError("invalid_state", "queue provenance is invalid")
    if unit.get("active_state") != "active" or unit.get("unit_file_state") not in {
        "enabled",
        "disabled",
    }:
        raise TransactionError("invalid_state", "queue provenance is invalid")
    if not isinstance(unit.get("user"), str) or not IDENTITY_RE.fullmatch(unit["user"]):
        raise TransactionError("invalid_state", "queue provenance is invalid")
    if not isinstance(unit.get("group"), str) or not IDENTITY_RE.fullmatch(
        unit["group"]
    ):
        raise TransactionError("invalid_state", "queue provenance is invalid")
    for key in ("uid", "gid"):
        item = unit.get(key)
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise TransactionError("invalid_state", "queue provenance is invalid")
    if not isinstance(unit.get("unit_fingerprint"), str) or not SHA256_RE.fullmatch(
        unit["unit_fingerprint"]
    ):
        raise TransactionError("invalid_state", "queue provenance is invalid")
    queue_root = validate_directory_identity(value["queue_root"], "queue root")
    quarantine_root = validate_directory_identity(
        value["quarantine_root"], "quarantine root"
    )
    # The service must be able to traverse the queue root after the child is
    # created.  Accept only the two documented production shapes: world-
    # traversable 0755, or 0750 grouped to the exact service GID.
    if not (
        queue_root["mode"] == 0o755
        or (queue_root["mode"] == 0o750 and queue_root["gid"] == unit["gid"])
    ):
        raise TransactionError(
            "invalid_state", "queue root is not traversable by the collector"
        )
    if quarantine_root["mode"] != 0o700:
        raise TransactionError("invalid_state", "quarantine root is not private")
    return {
        "machine_fingerprint": machine,
        "package": {"name": PACKAGE_NAME, "version": version},
        "service": dict(unit),
        "queue_root": queue_root,
        "quarantine_root": quarantine_root,
    }


class LocalSystem:
    """Capture the host/package/service and support-root identity."""

    def __init__(self, *, owner_uid: int = 0) -> None:
        self.owner_uid = owner_uid

    def capture(self, service: str, expected_version: str) -> dict[str, Any]:
        observed_version = package_version()
        if observed_version != expected_version:
            raise TransactionError("package_drift", "collector package version changed")
        queue, quarantine = validate_support_roots(owner_uid=self.owner_uid)
        return validate_provenance(
            {
                "machine_fingerprint": machine_fingerprint(owner_uid=self.owner_uid),
                "package": {"name": PACKAGE_NAME, "version": observed_version},
                "service": service_provenance(service, owner_uid=self.owner_uid),
                "queue_root": queue,
                "quarantine_root": quarantine,
            },
            service,
        )

    def verify(self, expected: Mapping[str, Any]) -> None:
        actual = self.capture(
            str(expected["service"]["name"]), str(expected["package"]["version"])
        )
        if actual != expected:
            raise TransactionError(
                "provenance_drift",
                "machine, package, service, or queue-root provenance changed",
            )


def verify_boundary(
    system: Any, expected: Mapping[str, Any], *, owner_uid: int
) -> None:
    queue, quarantine = validate_support_roots(owner_uid=owner_uid)
    if queue != expected["queue_root"] or quarantine != expected["quarantine_root"]:
        raise TransactionError(
            "provenance_drift", "queue support-root identity changed"
        )
    require_service_traversal(
        QUEUE_ROOT,
        service_uid=int(expected["service"]["uid"]),
        service_gid=int(expected["service"]["gid"]),
    )
    system.verify(expected)


def acquire_lock(*, owner_uid: int, owner_gid: int) -> BinaryIO:
    path = STATE_ROOT / ".transaction.lock"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
        opened = os.fstat(descriptor)
        named = os.lstat(path)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_dev != named.st_dev
            or opened.st_ino != named.st_ino
        ):
            os.close(descriptor)
            raise TransactionError("lock_failed", "queue transaction lock is unsafe")
        os.fchown(descriptor, owner_uid, owner_gid)
        os.fchmod(descriptor, 0o600)
        handle = os.fdopen(descriptor, "r+b", buffering=0)
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle
    except BlockingIOError as exc:
        raise TransactionError(
            "transaction_busy", "another queue transaction is active"
        ) from exc
    except OSError as exc:
        raise TransactionError("lock_failed", "queue transaction lock failed") from exc


def current_path() -> Path:
    return STATE_ROOT / "current.json"


def load_current(*, owner_uid: int, required: bool) -> dict[str, Any] | None:
    path = current_path()
    if not path.exists():
        if required:
            raise TransactionError(
                "invalid_state", "current queue transaction is unavailable"
            )
        return None
    value, _ = read_private_json(path, label="current transaction", owner_uid=owner_uid)
    if (
        set(value) != {"schema_version", "generation", "manifest_sha256"}
        or value.get("schema_version") != CURRENT_SCHEMA
        or not isinstance(value.get("generation"), str)
        or not GENERATION_RE.fullmatch(value["generation"])
        or not isinstance(value.get("manifest_sha256"), str)
        or not SHA256_RE.fullmatch(value["manifest_sha256"])
    ):
        raise TransactionError("invalid_state", "current queue transaction is invalid")
    return value


def install_current(
    generation: str,
    manifest_payload: bytes,
    *,
    owner_uid: int,
    owner_gid: int,
) -> None:
    write_atomic_private(
        current_path(),
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


def release_current(generation: str, *, owner_uid: int) -> None:
    current = load_current(owner_uid=owner_uid, required=True)
    if current is None or current["generation"] != generation:
        raise TransactionError(
            "invalid_state", "current queue generation does not match"
        )
    try:
        os.unlink(current_path())
        fsync_directory(STATE_ROOT)
    except OSError as exc:
        raise TransactionError(
            "state_write_failed", "current queue state could not be released"
        ) from exc


def create_generation(generation: str, *, owner_uid: int, owner_gid: int) -> Path:
    path = STATE_ROOT / f"generation-{generation}"
    try:
        os.mkdir(path, 0o700)
        os.chown(path, owner_uid, owner_gid, follow_symlinks=False)
        os.chmod(path, 0o700, follow_symlinks=False)
        fsync_directory(STATE_ROOT)
    except OSError as exc:
        raise TransactionError(
            "state_write_failed", "queue generation could not be created"
        ) from exc
    assert_private_directory(path, owner_uid=owner_uid, label="generation directory")
    return path


def generation_manifest_path(generation: str) -> Path:
    return STATE_ROOT / f"generation-{generation}" / "manifest.json"


def journal_path(generation: str) -> Path:
    return STATE_ROOT / f"generation-{generation}" / "journal.json"


def validate_manifest(value: Any, path: Path, *, owner_uid: int) -> dict[str, Any]:
    keys = {
        "schema_version",
        "generation",
        "created_at",
        "state_root",
        "owner_uid",
        "fingerprint",
        "service",
        "expected_package_version",
        "provenance",
    }
    if (
        not isinstance(value, dict)
        or set(value) != keys
        or value.get("schema_version") != STATE_SCHEMA
    ):
        raise TransactionError("invalid_state", "queue transaction manifest is invalid")
    generation = value.get("generation")
    if not isinstance(generation, str) or not GENERATION_RE.fullmatch(generation):
        raise TransactionError(
            "invalid_state", "queue transaction generation is invalid"
        )
    if path != generation_manifest_path(generation):
        raise TransactionError(
            "invalid_state", "queue transaction manifest path is invalid"
        )
    if (
        value.get("state_root") != str(STATE_ROOT)
        or value.get("owner_uid") != owner_uid
    ):
        raise TransactionError(
            "invalid_state", "queue transaction host binding is invalid"
        )
    if not isinstance(value.get("created_at"), str) or not UTC_RE.fullmatch(
        value["created_at"]
    ):
        raise TransactionError(
            "invalid_state", "queue transaction timestamp is invalid"
        )
    fingerprint = validate_fingerprint(value.get("fingerprint"))
    service = validate_service(value.get("service"))
    version = validate_version(value.get("expected_package_version"))
    provenance = validate_provenance(value.get("provenance"), service)
    if provenance["package"]["version"] != version:
        raise TransactionError(
            "invalid_state", "queue transaction package binding is invalid"
        )
    if (
        provenance["queue_root"]["uid"] != owner_uid
        or provenance["quarantine_root"]["uid"] != owner_uid
    ):
        raise TransactionError(
            "invalid_state", "queue transaction root ownership is invalid"
        )
    return {
        "schema_version": STATE_SCHEMA,
        "generation": generation,
        "created_at": value["created_at"],
        "state_root": str(STATE_ROOT),
        "owner_uid": owner_uid,
        "fingerprint": fingerprint,
        "service": service,
        "expected_package_version": version,
        "provenance": provenance,
    }


def load_manifest(path: Path, *, owner_uid: int) -> tuple[dict[str, Any], bytes]:
    value, payload = read_private_json(
        path, label="queue transaction manifest", owner_uid=owner_uid
    )
    return validate_manifest(value, path, owner_uid=owner_uid), payload


def validate_queue_identity(value: Any, fingerprint: str) -> dict[str, Any]:
    legacy_keys = {"device", "inode", "uid", "gid", "mode", "fingerprint"}
    keys = legacy_keys | {"ctime_ns"}
    if (
        not isinstance(value, dict)
        or set(value) not in (legacy_keys, keys)
        or value.get("fingerprint") != fingerprint
    ):
        raise TransactionError("invalid_state", "created queue identity is invalid")
    result: dict[str, Any] = {"fingerprint": fingerprint}
    for key in legacy_keys - {"fingerprint"}:
        item = value[key]
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise TransactionError("invalid_state", "created queue identity is invalid")
        result[key] = item
    ctime_ns = value.get("ctime_ns")
    if ctime_ns is not None and (
        isinstance(ctime_ns, bool) or not isinstance(ctime_ns, int) or ctime_ns < 0
    ):
        raise TransactionError("invalid_state", "created queue identity is invalid")
    # Journals written before ctime binding remain recoverable, but the missing
    # value makes exact deletion ineligible and therefore forces quarantine.
    result["ctime_ns"] = ctime_ns
    if result["mode"] > 0o7777:
        raise TransactionError("invalid_state", "created queue identity is invalid")
    return result


def validate_quarantine_identity(value: Any) -> dict[str, Any]:
    keys = {"device", "inode", "uid", "gid", "mode", "kind"}
    kinds = {"directory", "regular", "symlink", "other"}
    if (
        not isinstance(value, dict)
        or set(value) != keys
        or value.get("kind") not in kinds
    ):
        raise TransactionError("invalid_state", "quarantine identity is invalid")
    result: dict[str, Any] = {"kind": value["kind"]}
    for key in keys - {"kind"}:
        item = value[key]
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise TransactionError("invalid_state", "quarantine identity is invalid")
        result[key] = item
    if result["mode"] > 0o7777:
        raise TransactionError("invalid_state", "quarantine identity is invalid")
    return result


def initial_journal(generation: str) -> dict[str, Any]:
    return {
        "schema_version": JOURNAL_SCHEMA,
        "generation": generation,
        "phase": "prepared",
        "intent": None,
        "created_queue": None,
        "disposition": None,
        "quarantine": None,
        "updated_at": utc_now(),
    }


def validate_journal(value: Any, generation: str, fingerprint: str) -> dict[str, Any]:
    keys = {
        "schema_version",
        "generation",
        "phase",
        "intent",
        "created_queue",
        "disposition",
        "quarantine",
        "updated_at",
    }
    phases = {
        "prepared",
        "creating",
        "applied",
        "restoring",
        "restored",
        "recovery_required",
    }
    intents = {None, "create", "remove", "quarantine"}
    dispositions = {None, "removed", "quarantined", "already_absent"}
    if (
        not isinstance(value, dict)
        or set(value) != keys
        or value.get("schema_version") != JOURNAL_SCHEMA
        or value.get("generation") != generation
        or value.get("phase") not in phases
        or value.get("intent") not in intents
        or value.get("disposition") not in dispositions
        or not isinstance(value.get("updated_at"), str)
        or not UTC_RE.fullmatch(value["updated_at"])
    ):
        raise TransactionError("invalid_state", "queue transaction journal is invalid")
    created = value["created_queue"]
    quarantine = value["quarantine"]
    if created is not None:
        created = validate_queue_identity(created, fingerprint)
    if quarantine is not None:
        quarantine = validate_quarantine_identity(quarantine)
    if value["disposition"] == "quarantined" and quarantine is None:
        raise TransactionError("invalid_state", "queue transaction journal is invalid")
    if value["disposition"] != "quarantined" and quarantine is not None:
        raise TransactionError("invalid_state", "queue transaction journal is invalid")
    if value["phase"] == "prepared" and any(
        item is not None
        for item in (value["intent"], created, value["disposition"], quarantine)
    ):
        raise TransactionError("invalid_state", "queue transaction journal is invalid")
    if value["phase"] == "applied" and (
        value["intent"] is not None
        or created is None
        or value["disposition"] is not None
        or quarantine is not None
    ):
        raise TransactionError("invalid_state", "queue transaction journal is invalid")
    if value["phase"] == "restored" and (
        value["intent"] is not None or value["disposition"] is None
    ):
        raise TransactionError("invalid_state", "queue transaction journal is invalid")
    return {**value, "created_queue": created, "quarantine": quarantine}


def load_journal(document: Mapping[str, Any], *, owner_uid: int) -> dict[str, Any]:
    value, _ = read_private_json(
        journal_path(str(document["generation"])),
        label="queue transaction journal",
        owner_uid=owner_uid,
    )
    return validate_journal(
        value, str(document["generation"]), str(document["fingerprint"])
    )


def require_current(
    document: Mapping[str, Any], manifest_payload: bytes, *, owner_uid: int
) -> None:
    current = load_current(owner_uid=owner_uid, required=True)
    if (
        current is None
        or current["generation"] != document["generation"]
        or not hmac.compare_digest(
            current["manifest_sha256"], sha256_bytes(manifest_payload)
        )
    ):
        raise TransactionError(
            "invalid_state", "current queue generation does not match"
        )


def after_checkpoint(_phase: str, _intent: str | None) -> None:
    """Test seam reached only after the journal update is durable."""


def after_queue_side_effect(_operation: str) -> None:
    """Test seam immediately after a queue filesystem side effect."""


def write_journal(
    document: Mapping[str, Any],
    manifest_payload: bytes,
    journal: Mapping[str, Any],
    *,
    owner_uid: int,
    owner_gid: int,
    invoke_hook: bool = True,
) -> dict[str, Any]:
    require_current(document, manifest_payload, owner_uid=owner_uid)
    updated = {**journal, "updated_at": utc_now()}
    normalized = validate_journal(
        updated, str(document["generation"]), str(document["fingerprint"])
    )
    write_atomic_private(
        journal_path(str(document["generation"])),
        json_bytes(normalized),
        owner_uid=owner_uid,
        owner_gid=owner_gid,
    )
    if invoke_hook:
        after_checkpoint(str(normalized["phase"]), normalized["intent"])
    return normalized


def checkpoint(
    document: Mapping[str, Any],
    manifest_payload: bytes,
    journal: Mapping[str, Any],
    *,
    owner_uid: int,
    owner_gid: int,
    **changes: Any,
) -> dict[str, Any]:
    return write_journal(
        document,
        manifest_payload,
        {**journal, **changes},
        owner_uid=owner_uid,
        owner_gid=owner_gid,
    )


def queue_target(fingerprint: str) -> Path:
    return QUEUE_ROOT / fingerprint


def quarantine_name(generation: str, fingerprint: str) -> str:
    return f"generation-{generation}-{fingerprint}"


def quarantine_target(generation: str, fingerprint: str) -> Path:
    return QUARANTINE_ROOT / quarantine_name(generation, fingerprint)


def queue_identity(path: Path, fingerprint: str) -> dict[str, Any]:
    info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise TransactionError("queue_drift", "created queue is not a directory")
    return {
        "device": info.st_dev,
        "inode": info.st_ino,
        "uid": info.st_uid,
        "gid": info.st_gid,
        "mode": stat.S_IMODE(info.st_mode),
        "ctime_ns": info.st_ctime_ns,
        "fingerprint": fingerprint,
    }


def directory_identity_matches(
    info: os.stat_result, expected: Mapping[str, Any]
) -> bool:
    return (
        stat.S_ISDIR(info.st_mode)
        and info.st_dev == expected["device"]
        and info.st_ino == expected["inode"]
        and info.st_uid == expected["uid"]
        and info.st_gid == expected["gid"]
        and stat.S_IMODE(info.st_mode) == expected["mode"]
    )


def create_queue(
    fingerprint: str,
    *,
    service_uid: int,
    service_gid: int,
    expected_root: Mapping[str, Any],
) -> dict[str, Any]:
    root_flags = (
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    )
    if hasattr(os, "O_NOFOLLOW"):
        root_flags |= os.O_NOFOLLOW
    root_fd = os.open(QUEUE_ROOT, root_flags)
    queue_fd = -1
    try:
        if not directory_identity_matches(os.fstat(root_fd), expected_root):
            raise TransactionError(
                "provenance_drift", "queue root changed before directory creation"
            )
        os.mkdir(fingerprint, 0o700, dir_fd=root_fd)
        queue_fd = os.open(fingerprint, root_flags, dir_fd=root_fd)
        os.fchown(queue_fd, service_uid, service_gid)
        os.fchmod(queue_fd, 0o700)
        os.fsync(queue_fd)
        os.fsync(root_fd)
        info = os.fstat(queue_fd)
        named = os.stat(fingerprint, dir_fd=root_fd, follow_symlinks=False)
        if (
            info.st_dev != named.st_dev
            or info.st_ino != named.st_ino
            or info.st_uid != service_uid
            or info.st_gid != service_gid
            or stat.S_IMODE(info.st_mode) != 0o700
            or not directory_identity_matches(os.fstat(root_fd), expected_root)
        ):
            raise TransactionError("queue_create_failed", "queue identity is incorrect")
        return {
            "device": info.st_dev,
            "inode": info.st_ino,
            "uid": info.st_uid,
            "gid": info.st_gid,
            "mode": stat.S_IMODE(info.st_mode),
            "ctime_ns": info.st_ctime_ns,
            "fingerprint": fingerprint,
        }
    except FileExistsError as exc:
        raise TransactionError(
            "queue_exists", "destination queue already exists"
        ) from exc
    except OSError as exc:
        raise TransactionError(
            "queue_create_failed", "destination queue could not be created"
        ) from exc
    finally:
        if queue_fd >= 0:
            os.close(queue_fd)
        os.close(root_fd)


def path_exists(path: Path) -> bool:
    try:
        os.lstat(path)
        return True
    except FileNotFoundError:
        return False


def created_queue_identity_matches(
    info: os.stat_result, expected: Mapping[str, Any]
) -> bool:
    ctime_ns = expected.get("ctime_ns")
    return (
        stat.S_ISDIR(info.st_mode)
        and not stat.S_ISLNK(info.st_mode)
        and info.st_dev == expected["device"]
        and info.st_ino == expected["inode"]
        and info.st_uid == expected["uid"]
        and info.st_gid == expected["gid"]
        and stat.S_IMODE(info.st_mode) == expected["mode"] == 0o700
        and isinstance(ctime_ns, int)
        and not isinstance(ctime_ns, bool)
        and info.st_ctime_ns == ctime_ns
    )


def exact_created_queue(path: Path, expected: Mapping[str, Any]) -> bool:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    return created_queue_identity_matches(info, expected) and path.name == expected[
        "fingerprint"
    ]


def queue_is_empty_and_stable(path: Path, expected: Mapping[str, Any]) -> bool:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return False
    try:
        before = os.fstat(descriptor)
        if not created_queue_identity_matches(before, expected):
            return False
        entries = os.listdir(descriptor)
        after = os.fstat(descriptor)
        return not entries and (
            before.st_dev,
            before.st_ino,
            before.st_uid,
            before.st_gid,
            stat.S_IMODE(before.st_mode),
            before.st_ctime_ns,
        ) == (
            after.st_dev,
            after.st_ino,
            after.st_uid,
            after.st_gid,
            stat.S_IMODE(after.st_mode),
            after.st_ctime_ns,
        )
    finally:
        os.close(descriptor)


def remove_exact_empty_quarantine(
    path: Path,
    expected: Mapping[str, Any],
    expected_root: Mapping[str, Any],
) -> bool:
    if path.parent != QUARANTINE_ROOT:
        raise TransactionError("invalid_state", "queue quarantine target is invalid")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    root_fd = -1
    queue_fd = -1
    try:
        root_fd = os.open(QUARANTINE_ROOT, flags)
        if not directory_identity_matches(os.fstat(root_fd), expected_root):
            raise TransactionError(
                "provenance_drift", "quarantine root changed before removal"
            )
        queue_fd = os.open(path.name, flags, dir_fd=root_fd)
        opened = os.fstat(queue_fd)
        named = os.stat(path.name, dir_fd=root_fd, follow_symlinks=False)
        if (
            opened.st_dev != expected["device"]
            or opened.st_ino != expected["inode"]
            or opened.st_uid != expected["uid"]
            or opened.st_gid != expected["gid"]
            or stat.S_IMODE(opened.st_mode) != expected["mode"] == 0o700
            or opened.st_dev != named.st_dev
            or opened.st_ino != named.st_ino
        ):
            return False
        if os.listdir(queue_fd):
            return False
        after = os.fstat(queue_fd)
        if (
            after.st_dev != opened.st_dev
            or after.st_ino != opened.st_ino
            or after.st_uid != opened.st_uid
            or after.st_gid != opened.st_gid
            or stat.S_IMODE(after.st_mode) != stat.S_IMODE(opened.st_mode)
        ):
            return False
        try:
            os.rmdir(path.name, dir_fd=root_fd)
        except OSError as exc:
            if exc.errno in {errno.ENOTEMPTY, errno.EEXIST}:
                return False
            raise
        os.fsync(root_fd)
        try:
            os.stat(path.name, dir_fd=root_fd, follow_symlinks=False)
        except FileNotFoundError:
            return True
        raise TransactionError(
            "restore_failed", "retired queue path reappeared during removal"
        )
    except TransactionError:
        raise
    except OSError as exc:
        raise TransactionError(
            "restore_failed", "retired empty queue could not be removed"
        ) from exc
    finally:
        if queue_fd >= 0:
            os.close(queue_fd)
        if root_fd >= 0:
            os.close(root_fd)


def quarantine_kind(mode: int) -> str:
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISREG(mode):
        return "regular"
    if stat.S_ISLNK(mode):
        return "symlink"
    return "other"


def filesystem_entry_identity(path: Path) -> dict[str, Any]:
    info = os.lstat(path)
    return {
        "device": info.st_dev,
        "inode": info.st_ino,
        "uid": info.st_uid,
        "gid": info.st_gid,
        "mode": stat.S_IMODE(info.st_mode),
        "kind": quarantine_kind(info.st_mode),
    }


def protect_quarantine(
    path: Path,
    *,
    owner_uid: int,
    owner_gid: int,
    expected_root: Mapping[str, Any],
    expected_entry: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if path.parent != QUARANTINE_ROOT:
        raise TransactionError("invalid_state", "queue quarantine target is invalid")
    root_flags = (
        os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    )
    if hasattr(os, "O_NOFOLLOW"):
        root_flags |= os.O_NOFOLLOW
    root_fd = os.open(QUARANTINE_ROOT, root_flags)
    descriptor = -1
    try:
        if not directory_identity_matches(os.fstat(root_fd), expected_root):
            raise TransactionError(
                "provenance_drift", "quarantine root changed before protection"
            )
        info = os.stat(path.name, dir_fd=root_fd, follow_symlinks=False)
        observed = {
            "device": info.st_dev,
            "inode": info.st_ino,
            "uid": info.st_uid,
            "gid": info.st_gid,
            "mode": stat.S_IMODE(info.st_mode),
            "kind": quarantine_kind(info.st_mode),
        }
        if info.st_dev != expected_root["device"]:
            raise TransactionError(
                "quarantine_collision", "queue quarantine crosses a mount boundary"
            )
        if expected_entry is not None and (
            observed["device"] != expected_entry["device"]
            or observed["inode"] != expected_entry["inode"]
            or observed["kind"] != expected_entry.get("kind", "directory")
        ):
            raise TransactionError(
                "quarantine_collision", "queue quarantine identity is unexpected"
            )
        kind = observed["kind"]
        if kind == "directory":
            flags = root_flags
            descriptor = os.open(path.name, flags, dir_fd=root_fd)
            opened = os.fstat(descriptor)
            if opened.st_dev != info.st_dev or opened.st_ino != info.st_ino:
                raise TransactionError(
                    "quarantine_collision", "queue quarantine changed before protection"
                )
            os.fchown(descriptor, owner_uid, owner_gid)
            os.fchmod(descriptor, 0o700)
            os.fsync(descriptor)
        elif kind == "regular":
            flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(path.name, flags, dir_fd=root_fd)
            opened = os.fstat(descriptor)
            if opened.st_dev != info.st_dev or opened.st_ino != info.st_ino:
                raise TransactionError(
                    "quarantine_collision", "queue quarantine changed before protection"
                )
            os.fchown(descriptor, owner_uid, owner_gid)
            os.fchmod(descriptor, 0o600)
            os.fsync(descriptor)
        elif kind == "symlink":
            os.chown(
                path.name,
                owner_uid,
                owner_gid,
                dir_fd=root_fd,
                follow_symlinks=False,
            )
        else:
            os.chown(
                path.name,
                owner_uid,
                owner_gid,
                dir_fd=root_fd,
                follow_symlinks=False,
            )
            os.chmod(
                path.name,
                0o600,
                dir_fd=root_fd,
                follow_symlinks=False,
            )
        os.fsync(root_fd)
        final = os.stat(path.name, dir_fd=root_fd, follow_symlinks=False)
        if (
            final.st_dev != info.st_dev
            or final.st_ino != info.st_ino
            or final.st_uid != owner_uid
            or final.st_gid != owner_gid
            or quarantine_kind(final.st_mode) != kind
            or (kind == "directory" and stat.S_IMODE(final.st_mode) != 0o700)
            or (
                kind not in {"directory", "symlink"}
                and stat.S_IMODE(final.st_mode) != 0o600
            )
            or not directory_identity_matches(os.fstat(root_fd), expected_root)
        ):
            raise TransactionError(
                "quarantine_failed", "queue quarantine protection is incomplete"
            )
        return {
            "device": final.st_dev,
            "inode": final.st_ino,
            "uid": final.st_uid,
            "gid": final.st_gid,
            "mode": stat.S_IMODE(final.st_mode),
            "kind": kind,
        }
    except TransactionError:
        raise
    except OSError as exc:
        raise TransactionError(
            "quarantine_failed", "queue quarantine could not be protected"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(root_fd)


def move_to_quarantine(
    source: Path,
    destination: Path,
    *,
    expected_queue_root: Mapping[str, Any],
    expected_quarantine_root: Mapping[str, Any],
    expected_entry: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if source.parent != QUEUE_ROOT or destination.parent != QUARANTINE_ROOT:
        raise TransactionError("invalid_state", "queue rename target is invalid")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    queue_fd = -1
    quarantine_fd = -1
    source_fd = -1
    opened_source: os.stat_result | None = None
    try:
        queue_fd = os.open(QUEUE_ROOT, flags)
        quarantine_fd = os.open(QUARANTINE_ROOT, flags)
        if not directory_identity_matches(
            os.fstat(queue_fd), expected_queue_root
        ) or not directory_identity_matches(
            os.fstat(quarantine_fd), expected_quarantine_root
        ):
            raise TransactionError(
                "provenance_drift", "queue support root changed before quarantine"
            )
        try:
            os.stat(destination.name, dir_fd=quarantine_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise TransactionError(
                "quarantine_collision", "deterministic quarantine already exists"
            )
        if expected_entry is not None:
            source_fd = os.open(source.name, flags, dir_fd=queue_fd)
            opened_source = os.fstat(source_fd)
            named_source = os.stat(
                source.name, dir_fd=queue_fd, follow_symlinks=False
            )
            if (
                not created_queue_identity_matches(opened_source, expected_entry)
                or (
                    opened_source.st_dev,
                    opened_source.st_ino,
                    opened_source.st_ctime_ns,
                )
                != (
                    named_source.st_dev,
                    named_source.st_ino,
                    named_source.st_ctime_ns,
                )
                or os.listdir(source_fd)
            ):
                raise TransactionError(
                    "queue_drift", "created queue changed before retirement"
                )
        os.rename(
            source.name,
            destination.name,
            src_dir_fd=queue_fd,
            dst_dir_fd=quarantine_fd,
        )
        os.fsync(queue_fd)
        os.fsync(quarantine_fd)
        if not directory_identity_matches(
            os.fstat(queue_fd), expected_queue_root
        ) or not directory_identity_matches(
            os.fstat(quarantine_fd), expected_quarantine_root
        ):
            raise TransactionError(
                "provenance_drift", "queue support root changed during quarantine"
            )
        moved = os.stat(
            destination.name, dir_fd=quarantine_fd, follow_symlinks=False
        )
        if opened_source is not None and (
            moved.st_dev != opened_source.st_dev
            or moved.st_ino != opened_source.st_ino
            or moved.st_uid != opened_source.st_uid
            or moved.st_gid != opened_source.st_gid
            or stat.S_IMODE(moved.st_mode) != stat.S_IMODE(opened_source.st_mode)
        ):
            raise TransactionError(
                "queue_drift", "retired queue identity is incorrect"
            )
        return {
            "device": moved.st_dev,
            "inode": moved.st_ino,
            "uid": moved.st_uid,
            "gid": moved.st_gid,
            "mode": stat.S_IMODE(moved.st_mode),
            "kind": quarantine_kind(moved.st_mode),
        }
    except TransactionError:
        raise
    except OSError as exc:
        raise TransactionError(
            "quarantine_failed", "queue could not be quarantined atomically"
        ) from exc
    finally:
        if source_fd >= 0:
            os.close(source_fd)
        if quarantine_fd >= 0:
            os.close(quarantine_fd)
        if queue_fd >= 0:
            os.close(queue_fd)


def quarantine_queue(
    source: Path,
    destination: Path,
    *,
    owner_uid: int,
    owner_gid: int,
    expected_queue_root: Mapping[str, Any],
    expected_quarantine_root: Mapping[str, Any],
) -> dict[str, Any]:
    moved_identity = move_to_quarantine(
        source,
        destination,
        expected_queue_root=expected_queue_root,
        expected_quarantine_root=expected_quarantine_root,
    )
    return protect_quarantine(
        destination,
        owner_uid=owner_uid,
        owner_gid=owner_gid,
        expected_root=expected_quarantine_root,
        expected_entry=moved_identity,
    )


def prepare_state(
    *,
    generation: str,
    fingerprint: str,
    service: str,
    expected_version: str,
    provenance: Mapping[str, Any],
    owner_uid: int,
    owner_gid: int,
) -> tuple[dict[str, Any], bytes]:
    directory = create_generation(generation, owner_uid=owner_uid, owner_gid=owner_gid)
    document = validate_manifest(
        {
            "schema_version": STATE_SCHEMA,
            "generation": generation,
            "created_at": utc_now(),
            "state_root": str(STATE_ROOT),
            "owner_uid": owner_uid,
            "fingerprint": fingerprint,
            "service": service,
            "expected_package_version": expected_version,
            "provenance": dict(provenance),
        },
        directory / "manifest.json",
        owner_uid=owner_uid,
    )
    payload = json_bytes(document)
    write_exclusive(
        directory / "manifest.json",
        payload,
        mode=0o600,
        owner_uid=owner_uid,
        owner_gid=owner_gid,
    )
    write_exclusive(
        directory / "journal.json",
        json_bytes(initial_journal(generation)),
        mode=0o600,
        owner_uid=owner_uid,
        owner_gid=owner_gid,
    )
    install_current(generation, payload, owner_uid=owner_uid, owner_gid=owner_gid)
    return document, payload


def mark_recovery_required(
    document: Mapping[str, Any],
    manifest_payload: bytes,
    *,
    owner_uid: int,
    owner_gid: int,
) -> None:
    try:
        journal = load_journal(document, owner_uid=owner_uid)
        write_journal(
            document,
            manifest_payload,
            {**journal, "phase": "recovery_required"},
            owner_uid=owner_uid,
            owner_gid=owner_gid,
            invoke_hook=False,
        )
    except BaseException:
        pass


def observed_quarantine_identity(path: Path) -> dict[str, Any]:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise TransactionError(
            "restored_state_drift", "recorded queue quarantine is unavailable"
        ) from exc
    return {
        "device": info.st_dev,
        "inode": info.st_ino,
        "uid": info.st_uid,
        "gid": info.st_gid,
        "mode": stat.S_IMODE(info.st_mode),
        "kind": quarantine_kind(info.st_mode),
    }


def verify_completed_restore(
    document: Mapping[str, Any],
    journal: Mapping[str, Any],
    system: Any,
    *,
    owner_uid: int,
) -> None:
    verify_boundary(system, document["provenance"], owner_uid=owner_uid)
    source = queue_target(str(document["fingerprint"]))
    quarantine = quarantine_target(
        str(document["generation"]), str(document["fingerprint"])
    )
    if path_exists(source):
        raise TransactionError(
            "restored_state_drift", "completed queue restore has an active path"
        )
    if journal["disposition"] == "quarantined":
        expected = journal["quarantine"]
        if expected is None or observed_quarantine_identity(quarantine) != expected:
            raise TransactionError(
                "restored_state_drift", "recorded queue quarantine has drifted"
            )
    elif path_exists(quarantine):
        raise TransactionError(
            "restored_state_drift",
            "completed queue restore has an unexpected quarantine",
        )


def restore_from_document(
    document: Mapping[str, Any],
    manifest_payload: bytes,
    system: Any,
    *,
    owner_uid: int,
    owner_gid: int,
) -> dict[str, Any]:
    require_current(document, manifest_payload, owner_uid=owner_uid)
    journal = load_journal(document, owner_uid=owner_uid)
    if journal["phase"] == "restored":
        verify_completed_restore(document, journal, system, owner_uid=owner_uid)
        release_current(str(document["generation"]), owner_uid=owner_uid)
        return {"status": "restored", "disposition": journal["disposition"]}
    verify_boundary(system, document["provenance"], owner_uid=owner_uid)
    source = queue_target(str(document["fingerprint"]))
    quarantine = quarantine_target(
        str(document["generation"]), str(document["fingerprint"])
    )
    source_exists = path_exists(source)
    quarantine_exists = path_exists(quarantine)
    if source_exists and quarantine_exists:
        raise TransactionError(
            "quarantine_collision", "queue and deterministic quarantine both exist"
        )

    disposition: str
    quarantine_identity: dict[str, Any] | None = None
    if not source_exists:
        if quarantine_exists:
            quarantine_identity = protect_quarantine(
                quarantine,
                owner_uid=owner_uid,
                owner_gid=owner_gid,
                expected_root=document["provenance"]["quarantine_root"],
                expected_entry=journal["created_queue"],
            )
            disposition = "quarantined"
        else:
            disposition = "already_absent"
    else:
        created = journal["created_queue"]
        removable = (
            created is not None
            and exact_created_queue(source, created)
            and queue_is_empty_and_stable(source, created)
        )
        if removable:
            journal = checkpoint(
                document,
                manifest_payload,
                journal,
                owner_uid=owner_uid,
                owner_gid=owner_gid,
                phase="restoring",
                intent="remove",
            )
            verify_boundary(system, document["provenance"], owner_uid=owner_uid)
            # Retire the active pathname atomically behind the root-only
            # quarantine boundary before the final exact/empty decision. A
            # crash or concurrent writer therefore preserves rather than
            # deletes the queue.
            retired_identity = move_to_quarantine(
                source,
                quarantine,
                expected_queue_root=document["provenance"]["queue_root"],
                expected_quarantine_root=document["provenance"]["quarantine_root"],
                expected_entry=created,
            )
            after_queue_side_effect("retire_rename")
            if remove_exact_empty_quarantine(
                quarantine,
                retired_identity,
                document["provenance"]["quarantine_root"],
            ):
                after_queue_side_effect("remove")
                disposition = "removed"
            else:
                removable = False
        if not removable:
            if not path_exists(quarantine):
                journal = checkpoint(
                    document,
                    manifest_payload,
                    journal,
                    owner_uid=owner_uid,
                    owner_gid=owner_gid,
                    phase="restoring",
                    intent="quarantine",
                )
                verify_boundary(system, document["provenance"], owner_uid=owner_uid)
                quarantine_identity = quarantine_queue(
                    source,
                    quarantine,
                    owner_uid=owner_uid,
                    owner_gid=owner_gid,
                    expected_queue_root=document["provenance"]["queue_root"],
                    expected_quarantine_root=document["provenance"]["quarantine_root"],
                )
            else:
                quarantine_identity = protect_quarantine(
                    quarantine,
                    owner_uid=owner_uid,
                    owner_gid=owner_gid,
                    expected_root=document["provenance"]["quarantine_root"],
                    expected_entry=journal["created_queue"],
                )
            after_queue_side_effect("quarantine")
            disposition = "quarantined"

    if path_exists(source):
        raise TransactionError(
            "restore_failed", "queue rollback left the active path present"
        )
    if disposition == "quarantined" and not path_exists(quarantine):
        raise TransactionError("restore_failed", "queue quarantine is unavailable")
    verify_boundary(system, document["provenance"], owner_uid=owner_uid)
    journal = checkpoint(
        document,
        manifest_payload,
        journal,
        owner_uid=owner_uid,
        owner_gid=owner_gid,
        phase="restored",
        intent=None,
        disposition=disposition,
        quarantine=quarantine_identity,
    )
    release_current(str(document["generation"]), owner_uid=owner_uid)
    return {"status": "restored", "disposition": journal["disposition"]}


def apply_queue(
    *,
    fingerprint: str,
    service: str,
    expected_package_version: str,
    system: Any | None = None,
    owner_uid: int = 0,
    owner_gid: int = 0,
) -> dict[str, Any]:
    fingerprint = validate_fingerprint(fingerprint)
    service = validate_service(service)
    expected_package_version = validate_version(expected_package_version)
    # Reject a pre-existing or unsafe destination before creating transaction
    # support state. The check is repeated after the transaction lock.
    validate_support_roots(owner_uid=owner_uid)
    if path_exists(queue_target(fingerprint)):
        raise TransactionError("queue_exists", "destination queue already exists")
    ensure_state_root(owner_uid=owner_uid, owner_gid=owner_gid)
    with acquire_lock(owner_uid=owner_uid, owner_gid=owner_gid):
        if load_current(owner_uid=owner_uid, required=False) is not None:
            raise TransactionError(
                "current_generation",
                "restore the current queue generation before another apply",
            )
        active_system = system or LocalSystem(owner_uid=owner_uid)
        support_queue, support_quarantine = validate_support_roots(owner_uid=owner_uid)
        provenance = validate_provenance(
            active_system.capture(service, expected_package_version), service
        )
        require_service_traversal(
            QUEUE_ROOT,
            service_uid=int(provenance["service"]["uid"]),
            service_gid=int(provenance["service"]["gid"]),
        )
        if (
            provenance["queue_root"] != support_queue
            or provenance["quarantine_root"] != support_quarantine
        ):
            raise TransactionError(
                "provenance_drift", "captured queue support-root identity is incorrect"
            )
        target = queue_target(fingerprint)
        generation = secrets.token_hex(16)
        quarantine = quarantine_target(generation, fingerprint)
        if path_exists(target):
            raise TransactionError("queue_exists", "destination queue already exists")
        if path_exists(quarantine):
            raise TransactionError(
                "quarantine_collision", "deterministic quarantine already exists"
            )
        document, manifest_payload = prepare_state(
            generation=generation,
            fingerprint=fingerprint,
            service=service,
            expected_version=expected_package_version,
            provenance=provenance,
            owner_uid=owner_uid,
            owner_gid=owner_gid,
        )
        try:
            journal = load_journal(document, owner_uid=owner_uid)
            journal = checkpoint(
                document,
                manifest_payload,
                journal,
                owner_uid=owner_uid,
                owner_gid=owner_gid,
                phase="creating",
                intent="create",
            )
            verify_boundary(active_system, document["provenance"], owner_uid=owner_uid)
            created = create_queue(
                fingerprint,
                service_uid=int(provenance["service"]["uid"]),
                service_gid=int(provenance["service"]["gid"]),
                expected_root=provenance["queue_root"],
            )
            after_queue_side_effect("create")
            verify_boundary(active_system, document["provenance"], owner_uid=owner_uid)
            checkpoint(
                document,
                manifest_payload,
                journal,
                owner_uid=owner_uid,
                owner_gid=owner_gid,
                phase="applied",
                intent=None,
                created_queue=created,
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
                rollback = {
                    "attempted": True,
                    "ok": True,
                    "disposition": restored["disposition"],
                }
            except BaseException:
                mark_recovery_required(
                    document,
                    manifest_payload,
                    owner_uid=owner_uid,
                    owner_gid=owner_gid,
                )
                rollback = {"attempted": True, "ok": False, "recovery_required": True}
            error = (
                original
                if isinstance(original, TransactionError)
                else TransactionError("apply_failed", "queue transaction apply failed")
            )
            error.generation = generation  # type: ignore[attr-defined]
            error.rollback = rollback  # type: ignore[attr-defined]
            raise error from original
        return {
            "ok": True,
            "operation": "apply",
            "status": "applied",
            "generation": generation,
            "fingerprint": fingerprint,
        }


def restore_queue(
    manifest_path: Path,
    *,
    system: Any | None = None,
    owner_uid: int = 0,
    owner_gid: int = 0,
) -> dict[str, Any]:
    manifest_path = absolute_path(str(manifest_path), "transaction manifest")
    first, first_payload = load_manifest(manifest_path, owner_uid=owner_uid)
    ensure_state_root(owner_uid=owner_uid, owner_gid=owner_gid)
    with acquire_lock(owner_uid=owner_uid, owner_gid=owner_gid):
        document, manifest_payload = load_manifest(manifest_path, owner_uid=owner_uid)
        if first != document or not hmac.compare_digest(
            first_payload, manifest_payload
        ):
            raise TransactionError(
                "manifest_changed", "queue manifest changed while locking"
            )
        journal = load_journal(document, owner_uid=owner_uid)
        current = load_current(owner_uid=owner_uid, required=False)
        if current is None and journal["phase"] == "restored":
            active_system = system or LocalSystem(owner_uid=owner_uid)
            verify_completed_restore(
                document, journal, active_system, owner_uid=owner_uid
            )
            return {
                "ok": True,
                "operation": "restore",
                "status": "restored",
                "generation": document["generation"],
                "disposition": journal["disposition"],
            }
        require_current(document, manifest_payload, owner_uid=owner_uid)
        active_system = system or LocalSystem(owner_uid=owner_uid)
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
            error = (
                original
                if isinstance(original, TransactionError)
                else TransactionError(
                    "restore_failed", "queue transaction restore failed"
                )
            )
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
            "disposition": restored["disposition"],
        }


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(description=__doc__, allow_abbrev=False)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    apply_parser = subparsers.add_parser("apply", allow_abbrev=False)
    apply_parser.add_argument("--fingerprint", required=True)
    apply_parser.add_argument("--service", required=True)
    apply_parser.add_argument("--expected-package-version", required=True)
    restore_parser = subparsers.add_parser("restore", allow_abbrev=False)
    restore_parser.add_argument("--manifest", required=True, type=Path)
    return parser


def signal_handler(_signum: int, _frame: Any) -> None:
    raise TransactionError("interrupted", "queue transaction was interrupted")


def install_signal_handlers() -> dict[int, Any]:
    previous: dict[int, Any] = {}
    for number in (signal.SIGINT, signal.SIGTERM):
        previous[number] = signal.getsignal(number)
        signal.signal(number, signal_handler)
    return previous


def restore_signal_handlers(previous: Mapping[int, Any]) -> None:
    for number, handler in previous.items():
        signal.signal(number, handler)


def main(argv: Sequence[str] | None = None) -> int:
    operation = "unknown"
    previous: dict[int, Any] = {}
    try:
        args = build_parser().parse_args(argv)
        operation = args.operation
        previous = install_signal_handlers()
        validate_runtime()
        result = (
            apply_queue(
                fingerprint=args.fingerprint,
                service=args.service,
                expected_package_version=args.expected_package_version,
            )
            if operation == "apply"
            else restore_queue(args.manifest)
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
                    "message": "unexpected queue transaction failure",
                },
            },
            stream=sys.stderr,
        )
        return 1
    finally:
        if previous:
            restore_signal_handlers(previous)


if __name__ == "__main__":
    raise SystemExit(main())
