#!/usr/bin/python3
"""Load a protected Galileo key file, validate routing, and exec the collector."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import shlex
import shutil
import socket
import stat
import sys
import urllib.parse
from pathlib import Path


MAX_SECRET_BYTES = 64 * 1024
MAX_SELECTOR_BYTES = 1024
MAX_EVIDENCE_BYTES = 64 * 1024
MAX_PROXY_ASSET_BYTES = 1024 * 1024
MAX_COLLECTOR_BINARY_BYTES = 1024 * 1024 * 1024
MIN_QUEUE_FREE_BYTES = 1_073_741_824
SHA256 = re.compile(r"^[0-9a-f]{64}$")
TINYPROXY_CONTROL = "tinyproxy-exact-connect-allowlist"
PROXY_PROBE_TIMEOUT_SECONDS = 3.0
MAX_PROXY_PROBE_BYTES = 8192
PROXY_ENVIRONMENT_NAMES = {
    "HTTP_PROXY",
    "http_proxy",
    "HTTPS_PROXY",
    "https_proxy",
    "ALL_PROXY",
    "all_proxy",
    "NO_PROXY",
    "no_proxy",
}


def valid_network_host(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        labels = host.rstrip(".").split(".")
        return (
            len(host.rstrip(".")) <= 253
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


def read_secret(path: Path) -> str:
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError("Galileo API-key file is not a readable regular file") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Galileo API-key file must be a single-link regular file")
        if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
            raise ValueError("Galileo API-key file must be owned by the service user")
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError(
                "Galileo API-key file permissions must be 0600 or stricter"
            )
        if not 1 <= info.st_size <= MAX_SECRET_BYTES:
            raise ValueError("Galileo API-key file size is outside the allowed range")
        chunks: list[bytes] = []
        remaining = MAX_SECRET_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 8192))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        after = os.fstat(descriptor)
        if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ) or len(data) != info.st_size:
            raise ValueError(
                "Galileo API-key file changed or could not be read completely"
            )
    finally:
        os.close(descriptor)
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError("Galileo API-key file must contain UTF-8 text") from exc
    if (
        len(lines) != 1
        or not lines[0]
        or any(ord(character) < 32 or ord(character) == 127 for character in lines[0])
    ):
        raise ValueError("Galileo API-key file must contain exactly one non-empty line")
    return lines[0]


def validate_endpoint(value: str) -> tuple[str, str]:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(
            "GALILEO_OTLP_TRACES_ENDPOINT contains unsafe characters"
        ) from exc
    if (
        not value
        or "\\" in value
        or any(character.isspace() or ord(character) == 127 for character in value)
    ):
        raise ValueError("GALILEO_OTLP_TRACES_ENDPOINT contains unsafe characters")
    try:
        parsed = urllib.parse.urlparse(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError(
            "GALILEO_OTLP_TRACES_ENDPOINT contains an invalid port"
        ) from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.netloc.endswith(":")
    ):
        raise ValueError(
            "GALILEO_OTLP_TRACES_ENDPOINT must be an HTTPS URL without credentials"
        )
    if not valid_network_host(parsed.hostname):
        raise ValueError("GALILEO_OTLP_TRACES_ENDPOINT contains an invalid hostname")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("GALILEO_OTLP_TRACES_ENDPOINT contains an invalid port")
    if parsed.params or parsed.query or parsed.fragment or not parsed.path.strip("/"):
        raise ValueError(
            "Galileo endpoint must contain an exact path and no query or fragment"
        )
    if urllib.parse.unquote(parsed.path) != parsed.path:
        raise ValueError("Galileo endpoint path must not contain encoded characters")
    for segment in parsed.path.split("/"):
        decoded = urllib.parse.unquote(segment)
        if (
            decoded in {".", ".."}
            or "\\" in decoded
            or any(
                ord(character) < 32 or ord(character) == 127 for character in decoded
            )
        ):
            raise ValueError("Galileo endpoint path contains an unsafe segment")
    host = parsed.hostname.lower()
    host_for_url = f"[{host}]" if ":" in host else host
    port_suffix = f":{port}" if port is not None and port != 443 else ""
    origin = f"https://{host_for_url}{port_suffix}"
    endpoint = urllib.parse.urlunparse(
        ("https", f"{host_for_url}{port_suffix}", parsed.path, "", "", "")
    )
    return origin, endpoint


def validate_expected_origin(value: str, endpoint_origin: str) -> str:
    if not value or value != value.strip():
        raise ValueError("GALILEO_EXPECTED_ORIGIN is required without outer whitespace")
    try:
        parsed = urllib.parse.urlparse(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("GALILEO_EXPECTED_ORIGIN contains an invalid port") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.params
        or parsed.path
        or parsed.query
        or parsed.fragment
        or not valid_network_host(parsed.hostname)
    ):
        raise ValueError("GALILEO_EXPECTED_ORIGIN must be an exact HTTPS origin")
    host = parsed.hostname.lower()
    host_for_url = f"[{host}]" if ":" in host else host
    port_suffix = f":{port}" if port is not None and port != 443 else ""
    canonical = f"https://{host_for_url}{port_suffix}"
    if value != canonical or canonical != endpoint_origin:
        raise ValueError("Galileo endpoint does not match GALILEO_EXPECTED_ORIGIN")
    return canonical


def selector_value(environment: dict[str, str], name: str) -> str:
    value = environment.get(name, "")
    if not value:
        return ""
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError:
        size = MAX_SELECTOR_BYTES + 1
    if (
        value != value.strip()
        or size > MAX_SELECTOR_BYTES
        or "\\" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(f"{name} contains unsafe selector content")
    return value


def validate_selectors(environment: dict[str, str]) -> tuple[str, str, str]:
    project_id = selector_value(environment, "GALILEO_PROJECT_ID")
    log_stream_id = selector_value(environment, "GALILEO_LOG_STREAM_ID")
    project_name = selector_value(environment, "GALILEO_PROJECT")
    log_stream_name = selector_value(environment, "GALILEO_LOG_STREAM")
    identifiers = bool(project_id) and bool(log_stream_id)
    names = bool(project_name) and bool(log_stream_name)
    partial_ids = bool(project_id) != bool(log_stream_id)
    partial_names = bool(project_name) != bool(log_stream_name)
    if partial_ids or partial_names or identifiers == names:
        raise ValueError(
            "configure exactly one complete Galileo project/Log stream selector pair"
        )
    if identifiers:
        return "ids", project_id, log_stream_id
    return "names", project_name, log_stream_name


def destination_fingerprint(endpoint: str, selector_pair: tuple[str, str, str]) -> str:
    kind, project, log_stream = selector_pair
    canonical = json.dumps(
        {
            "endpoint": endpoint,
            "log_stream": log_stream,
            "project": project,
            "selector_kind": kind,
            "version": 1,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def validate_declared_fingerprint(environment: dict[str, str], derived: str) -> str:
    declared = environment.get("GALILEO_DESTINATION_FINGERPRINT", "")
    if not SHA256.fullmatch(declared):
        raise ValueError(
            "GALILEO_DESTINATION_FINGERPRINT must be a lowercase SHA-256 digest"
        )
    if declared != derived:
        raise ValueError("GALILEO_DESTINATION_FINGERPRINT does not match the target")
    return declared


def read_protected_json(path: Path) -> dict[str, object]:
    if sys.platform.startswith("linux"):
        if not path.is_absolute():
            raise ValueError("tinyproxy evidence path must be absolute")
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise ValueError("tinyproxy evidence path is unavailable") from exc
        if resolved != path:
            raise ValueError("tinyproxy evidence path must be canonical")
        current = Path(path.anchor)
        for part in path.parts[1:-1]:
            current /= part
            info = os.lstat(current)
            if (
                stat.S_ISLNK(info.st_mode)
                or not stat.S_ISDIR(info.st_mode)
                or info.st_uid != 0
                or stat.S_IMODE(info.st_mode) & 0o022
            ):
                raise ValueError("tinyproxy evidence has an untrusted ancestor")
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError("tinyproxy evidence is not a readable regular file") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 1 <= before.st_size <= MAX_EVIDENCE_BYTES
        ):
            raise ValueError(
                "tinyproxy evidence must be protected, single-link, and bounded"
            )
        validate_evidence_access_metadata(before)
        data = os.read(descriptor, MAX_EVIDENCE_BYTES + 1)
        after = os.fstat(descriptor)
        if len(data) != before.st_size or (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError("tinyproxy evidence changed while being read")
    finally:
        os.close(descriptor)
    try:
        document = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("tinyproxy evidence must be valid bounded JSON") from exc
    if not isinstance(document, dict):
        raise ValueError("tinyproxy evidence must be a JSON object")
    return document


def validate_evidence_access_metadata(info: os.stat_result) -> None:
    """Require root-owned evidence readable only by the collector group."""

    mode = stat.S_IMODE(info.st_mode)
    euid = os.geteuid() if hasattr(os, "geteuid") else info.st_uid
    if sys.platform.startswith("linux"):
        groups = set(os.getgroups() if hasattr(os, "getgroups") else ())
        if hasattr(os, "getegid"):
            groups.add(os.getegid())
        if info.st_uid != 0 or mode != 0o440 or info.st_gid not in groups:
            raise ValueError(
                "tinyproxy evidence must be root-owned mode 0440 and grouped "
                "to the collector service"
            )
    elif info.st_uid not in {0, euid} or mode & 0o022:
        raise ValueError(
            "tinyproxy evidence must be owner-controlled and not writable by group/other"
        )


def descriptor_exec_supported() -> bool:
    supports_fd = getattr(os, "supports_fd", set())
    return (
        os.execve in supports_fd
        or callable(getattr(os, "fexecve", None))
        or (sys.platform.startswith("linux") and Path("/proc/self/fd").is_dir())
    )


def trusted_executable_path(path: Path) -> Path:
    """Require a canonical executable path with a trusted Linux path chain."""

    if not path.is_absolute() or str(Path(os.path.normpath(path))) != str(path):
        raise ValueError(
            "reviewed collector binary path must be canonical and absolute"
        )
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ValueError("reviewed collector binary is unavailable") from exc
    if resolved != path:
        raise ValueError("reviewed collector binary path must not contain links")

    if sys.platform.startswith("linux"):
        current = Path(path.anchor)
        for index, part in enumerate(path.parts[1:]):
            current /= part
            try:
                info = os.lstat(current)
            except OSError as exc:
                raise ValueError(
                    "reviewed collector binary path cannot be inspected"
                ) from exc
            final = index == len(path.parts[1:]) - 1
            if stat.S_ISLNK(info.st_mode):
                raise ValueError(
                    "reviewed collector binary path must not contain links"
                )
            if not final and not stat.S_ISDIR(info.st_mode):
                raise ValueError(
                    "reviewed collector binary has a non-directory ancestor"
                )
            if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
                raise ValueError(
                    "reviewed collector binary path must be root-owned and not "
                    "group/other-writable"
                )
    return path


def open_trusted_executable(
    path: Path,
    expected_sha256: str | None,
    *,
    expected_provenance: dict[str, int | str] | None = None,
) -> tuple[int, dict[str, int | str]]:
    """Open and hash one trusted collector executable without following links."""

    path = trusted_executable_path(path)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError(
            "reviewed collector binary is not a readable regular file"
        ) from exc
    try:
        before = os.fstat(descriptor)
        named = os.lstat(path)
        mode = stat.S_IMODE(before.st_mode)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_dev != named.st_dev
            or before.st_ino != named.st_ino
            or not mode & 0o111
            or before.st_size < 1
            or before.st_size > MAX_COLLECTOR_BINARY_BYTES
        ):
            raise ValueError(
                "reviewed collector binary must be a bounded single-link executable"
            )
        if sys.platform.startswith("linux") and (before.st_uid != 0 or mode & 0o022):
            raise ValueError(
                "reviewed collector binary must be root-owned and not "
                "group/other-writable"
            )

        digest = hashlib.sha256()
        remaining = MAX_COLLECTOR_BINARY_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            digest.update(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        if identity != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise ValueError("reviewed collector binary changed while being hashed")
        provenance: dict[str, int | str] = {
            "path": str(path),
            "device": before.st_dev,
            "inode": before.st_ino,
            "size": before.st_size,
            "mtime_ns": before.st_mtime_ns,
            "uid": before.st_uid,
            "mode": mode,
            "sha256": digest.hexdigest(),
        }
        if expected_sha256 is not None and provenance["sha256"] != expected_sha256:
            raise ValueError("custom collector binary evidence does not match")
        if expected_provenance is not None and provenance != expected_provenance:
            raise ValueError("reviewed collector binary changed before execution")
        os.lseek(descriptor, 0, os.SEEK_SET)
        return descriptor, provenance
    except BaseException:
        os.close(descriptor)
        raise


def regular_file_sha256(path: Path) -> str:
    """Compatibility helper used by evidence validation and regression tests."""

    descriptor, provenance = open_trusted_executable(path, None)
    os.close(descriptor)
    return str(provenance["sha256"])


def descriptor_exec(
    descriptor: int, arguments: list[str], environment: dict[str, str]
) -> None:
    """Execute exactly the verified descriptor or fail closed."""

    if os.execve in getattr(os, "supports_fd", set()):
        os.execve(descriptor, arguments, environment)
        return
    fexecve = getattr(os, "fexecve", None)
    if callable(fexecve):
        fexecve(descriptor, arguments, environment)
        return
    if sys.platform.startswith("linux") and Path("/proc/self/fd").is_dir():
        descriptor_path = Path("/proc/self/fd") / str(descriptor)
        opened = os.fstat(descriptor)
        linked = os.stat(descriptor_path)
        if (opened.st_dev, opened.st_ino) != (linked.st_dev, linked.st_ino):
            raise ValueError("verified collector descriptor cannot be executed safely")
        os.lseek(descriptor, 0, os.SEEK_SET)
        if os.read(descriptor, 4) != b"\x7fELF":
            raise ValueError(
                "the /proc descriptor fallback supports only an ELF collector binary"
            )
        os.lseek(descriptor, 0, os.SEEK_SET)
        # Keep CLOEXEC set. Linux resolves the already-open ELF descriptor for
        # exec before closing it, so the collector does not inherit an extra fd.
        os.execve(str(descriptor_path), arguments, environment)
        return
    raise ValueError("custom collector execution is unsupported on this platform")


def validate_galileo_proxy_url(value: str) -> tuple[str, str, int]:
    """Return the one supported exporter-local proxy URL and socket address."""

    if not value or value != value.strip() or "\\" in value:
        raise ValueError("GALILEO_PROXY_URL must be an explicit loopback HTTP URL")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("GALILEO_PROXY_URL contains an invalid port") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.netloc != f"127.0.0.1:{port}"
        or not 1 <= port <= 65535
    ):
        raise ValueError("GALILEO_PROXY_URL must be canonical http://127.0.0.1:PORT")
    return value, "127.0.0.1", port


def trusted_proxy_asset_path(path: Path, label: str) -> Path:
    if not path.is_absolute() or str(Path(os.path.normpath(path))) != str(path):
        raise ValueError(f"tinyproxy {label} path must be canonical and absolute")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"tinyproxy {label} is unavailable") from exc
    if resolved != path:
        raise ValueError(f"tinyproxy {label} path must not contain links")
    if sys.platform.startswith("linux"):
        current = Path(path.anchor)
        for index, part in enumerate(path.parts[1:]):
            current /= part
            try:
                info = os.lstat(current)
            except OSError as exc:
                raise ValueError(f"tinyproxy {label} path cannot be inspected") from exc
            final = index == len(path.parts[1:]) - 1
            if stat.S_ISLNK(info.st_mode):
                raise ValueError(f"tinyproxy {label} path must not contain links")
            if not final and not stat.S_ISDIR(info.st_mode):
                raise ValueError(f"tinyproxy {label} has a non-directory ancestor")
            if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
                raise ValueError(
                    f"tinyproxy {label} path must be root-owned and not "
                    "group/other-writable"
                )
    return path


def read_trusted_proxy_asset(
    path: Path,
    label: str,
    expected_provenance: dict[str, object] | None,
) -> tuple[bytes, dict[str, int | str]]:
    """Read a protected proxy config/filter and match its complete identity."""

    path = trusted_proxy_asset_path(path, label)
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"tinyproxy {label} is not a readable regular file") from exc
    try:
        before = os.fstat(descriptor)
        named = os.lstat(path)
        mode = stat.S_IMODE(before.st_mode)
        euid = os.geteuid() if hasattr(os, "geteuid") else before.st_uid
        allowed_owners = {0} if sys.platform.startswith("linux") else {0, euid}
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid not in allowed_owners
            or mode & 0o022
            or before.st_dev != named.st_dev
            or before.st_ino != named.st_ino
            or not 1 <= before.st_size <= MAX_PROXY_ASSET_BYTES
        ):
            raise ValueError(
                f"tinyproxy {label} must be protected, single-link, and bounded"
            )
        data = os.read(descriptor, MAX_PROXY_ASSET_BYTES + 1)
        after = os.fstat(descriptor)
        if len(data) != before.st_size or (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError(f"tinyproxy {label} changed while being read")
        provenance: dict[str, int | str] = {
            "path": str(path),
            "device": before.st_dev,
            "inode": before.st_ino,
            "size": before.st_size,
            "mtime_ns": before.st_mtime_ns,
            "uid": before.st_uid,
            "mode": mode,
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        if expected_provenance is not None and provenance != expected_provenance:
            raise ValueError(f"tinyproxy {label} identity or content has drifted")
        return data, provenance
    finally:
        os.close(descriptor)


def evidence_provenance(evidence: dict[str, object], label: str) -> dict[str, object]:
    value = evidence.get(label)
    keys = {
        "path",
        "device",
        "inode",
        "size",
        "mtime_ns",
        "uid",
        "mode",
        "sha256",
    }
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"tinyproxy evidence has invalid {label} provenance")
    if (
        not isinstance(value.get("path"), str)
        or not isinstance(value.get("sha256"), str)
        or not SHA256.fullmatch(str(value["sha256"]))
        or any(
            not isinstance(value.get(name), int) or isinstance(value.get(name), bool)
            for name in ("device", "inode", "size", "mtime_ns", "uid", "mode")
        )
    ):
        raise ValueError(f"tinyproxy evidence has invalid {label} provenance")
    return value


def tinyproxy_directives(data: bytes) -> dict[str, list[list[str]]]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("tinyproxy config must be UTF-8 text") from exc
    directives: dict[str, list[list[str]]] = {}
    for line_number, line in enumerate(text.splitlines(), 1):
        if any(ord(character) < 32 and character != "\t" for character in line):
            raise ValueError("tinyproxy config contains control characters")
        try:
            words = shlex.split(line, comments=True, posix=True)
        except ValueError as exc:
            raise ValueError(
                f"tinyproxy config has invalid quoting at line {line_number}"
            ) from exc
        if not words:
            continue
        directives.setdefault(words[0].casefold(), []).append(words[1:])
    return directives


def require_tinyproxy_directive(
    directives: dict[str, list[list[str]]], name: str, expected: list[str]
) -> None:
    values = directives.get(name.casefold())
    if values != [expected]:
        raise ValueError(
            f"tinyproxy config must contain exactly `{name} {' '.join(expected)}`"
        )


def validate_tinyproxy_config(
    data: bytes, *, proxy_port: int, filter_path: str
) -> None:
    directives = tinyproxy_directives(data)
    allowed_directives = {
        "allow",
        "connectport",
        "disableviaheader",
        "filter",
        "filtercasesensitive",
        "filterdefaultdeny",
        "filtertype",
        "filterurls",
        "group",
        "listen",
        "loglevel",
        "maxclients",
        "pidfile",
        "port",
        "syslog",
        "timeout",
        "user",
    }
    for forbidden in (
        "addheader",
        "basicauth",
        "deny",
        "filterextended",
        "include",
        "map",
        "reversebaseurl",
        "reversemagic",
        "reverseonly",
        "reversepath",
        "transparent",
        "upstream",
    ):
        if forbidden in directives:
            raise ValueError(f"tinyproxy config must not contain {forbidden}")
    unexpected = sorted(set(directives) - allowed_directives)
    if unexpected:
        raise ValueError(
            "tinyproxy config contains an unsupported directive: " + unexpected[0]
        )
    require_tinyproxy_directive(directives, "Listen", ["127.0.0.1"])
    require_tinyproxy_directive(directives, "Port", [str(proxy_port)])
    require_tinyproxy_directive(directives, "User", ["tinyproxy"])
    require_tinyproxy_directive(directives, "Group", ["tinyproxy"])
    require_tinyproxy_directive(directives, "Timeout", ["30"])
    require_tinyproxy_directive(directives, "MaxClients", ["32"])
    require_tinyproxy_directive(
        directives, "PidFile", ["/run/tinyproxy-galileo/tinyproxy.pid"]
    )
    require_tinyproxy_directive(directives, "Syslog", ["On"])
    require_tinyproxy_directive(directives, "LogLevel", ["Info"])
    require_tinyproxy_directive(directives, "Allow", ["127.0.0.1"])
    require_tinyproxy_directive(directives, "ConnectPort", ["443"])
    require_tinyproxy_directive(directives, "Filter", [filter_path])
    require_tinyproxy_directive(directives, "FilterType", ["ere"])
    require_tinyproxy_directive(directives, "FilterURLs", ["No"])
    require_tinyproxy_directive(directives, "FilterCaseSensitive", ["Yes"])
    require_tinyproxy_directive(directives, "FilterDefaultDeny", ["Yes"])
    require_tinyproxy_directive(directives, "DisableViaHeader", ["Yes"])


def exact_host_filter_rule(host: str) -> str:
    if host != host.casefold() or host.endswith(".") or not valid_network_host(host):
        raise ValueError(
            "tinyproxy allowed host must be one canonical lowercase hostname"
        )
    # Tinyproxy uses POSIX ERE. Escape every regex metacharacter while leaving
    # DNS hyphens literal so the expression is portable across ERE engines.
    return "^" + re.escape(host).replace(r"\-", "-") + "$"


def validate_tinyproxy_filter(data: bytes, allowed_host: str) -> None:
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("tinyproxy filter must be ASCII text") from exc
    rule = exact_host_filter_rule(allowed_host)
    if text not in {rule, rule + "\n"}:
        raise ValueError(
            "tinyproxy filter must contain only the exact escaped Galileo host"
        )


def proxy_connect_status(
    proxy_host: str,
    proxy_port: int,
    destination_host: str,
    *,
    timeout: float = PROXY_PROBE_TIMEOUT_SECONDS,
) -> int:
    """Issue one bounded, credential-free CONNECT and return its status code."""

    authority = f"{destination_host}:443"
    request = (
        f"CONNECT {authority} HTTP/1.1\r\n"
        f"Host: {authority}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    try:
        with socket.create_connection(
            (proxy_host, proxy_port), timeout=timeout
        ) as peer:
            peer.settimeout(timeout)
            peer.sendall(request)
            response = bytearray()
            while (
                b"\r\n\r\n" not in response and len(response) <= MAX_PROXY_PROBE_BYTES
            ):
                chunk = peer.recv(min(1024, MAX_PROXY_PROBE_BYTES + 1 - len(response)))
                if not chunk:
                    break
                response.extend(chunk)
    except (OSError, TimeoutError) as exc:
        raise ValueError("tinyproxy CONNECT probe could not complete") from exc
    if len(response) > MAX_PROXY_PROBE_BYTES or b"\r\n" not in response:
        raise ValueError("tinyproxy CONNECT probe returned an invalid response")
    first_line = bytes(response).split(b"\r\n", 1)[0]
    match = re.fullmatch(rb"HTTP/1[.]\d ([0-9]{3})(?: [\x20-\x7e]*)?", first_line)
    if not match:
        raise ValueError("tinyproxy CONNECT probe returned an invalid status line")
    return int(match.group(1))


def probe_tinyproxy(proxy_url: str, allowed_host: str) -> None:
    _, host, port = validate_galileo_proxy_url(proxy_url)
    denied = proxy_connect_status(host, port, "denied.invalid")
    if denied != 403:
        raise ValueError("tinyproxy deny probe did not return HTTP 403")
    allowed = proxy_connect_status(host, port, allowed_host)
    if not 200 <= allowed < 300:
        raise ValueError("tinyproxy allow probe did not establish CONNECT")


def validate_tinyproxy_contract(
    environment: dict[str, str],
    canonical_endpoint: str,
    *,
    run_probes: bool = True,
) -> dict[str, object]:
    """Validate the exact proxy target, protected assets, and live behavior."""

    endpoint = urllib.parse.urlsplit(canonical_endpoint)
    allowed_host = endpoint.hostname or ""
    if endpoint.port not in {None, 443}:
        raise ValueError("Galileo endpoint must use HTTPS port 443")
    exact_host_filter_rule(allowed_host)
    proxy_url, _, proxy_port = validate_galileo_proxy_url(
        environment.get("GALILEO_PROXY_URL", "")
    )
    raw_path = environment.get("GALILEO_TINYPROXY_EVIDENCE_FILE", "")
    if not raw_path or raw_path != raw_path.strip():
        raise ValueError("GALILEO_TINYPROXY_EVIDENCE_FILE is required")
    evidence = read_protected_json(Path(raw_path))
    expected_keys = {
        "schema_version",
        "control",
        "proxy_url",
        "allowed_connect_host",
        "allowed_connect_port",
        "binary",
        "config",
        "filter",
    }
    if set(evidence) != expected_keys or any(
        evidence.get(name) != expected
        for name, expected in {
            "schema_version": 1,
            "control": TINYPROXY_CONTROL,
            "proxy_url": proxy_url,
            "allowed_connect_host": allowed_host,
            "allowed_connect_port": 443,
        }.items()
    ):
        raise ValueError("tinyproxy evidence does not match the runtime contract")

    binary = evidence_provenance(evidence, "binary")
    descriptor, actual_binary = open_trusted_executable(
        Path(str(binary["path"])), str(binary["sha256"])
    )
    os.close(descriptor)
    if actual_binary != binary:
        raise ValueError("tinyproxy binary identity or content has drifted")

    config = evidence_provenance(evidence, "config")
    filter_evidence = evidence_provenance(evidence, "filter")
    config_data, _ = read_trusted_proxy_asset(
        Path(str(config["path"])), "config", config
    )
    filter_data, _ = read_trusted_proxy_asset(
        Path(str(filter_evidence["path"])), "filter", filter_evidence
    )
    validate_tinyproxy_filter(filter_data, allowed_host)
    validate_tinyproxy_config(
        config_data,
        proxy_port=proxy_port,
        filter_path=str(filter_evidence["path"]),
    )
    if run_probes:
        probe_tinyproxy(proxy_url, allowed_host)
    return evidence


def restricted_transport_environment(
    environment: dict[str, str], _control: str | None = None
) -> dict[str, str]:
    """Strip every ambient proxy and bypass variable from the collector child."""

    restricted = dict(environment)
    for name in PROXY_ENVIRONMENT_NAMES:
        restricted.pop(name, None)
    return restricted


def validate_queue_directory(raw_path: str, fingerprint: str) -> Path:
    if not raw_path or raw_path != raw_path.strip():
        raise ValueError("GALILEO_QUEUE_STORAGE_DIRECTORY is required")
    path = Path(raw_path)
    if not path.is_absolute() or path.name != fingerprint:
        raise ValueError(
            "Galileo queue directory must be absolute and destination-fingerprinted"
        )
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ValueError("Galileo queue directory does not exist") from exc
    if resolved != path:
        raise ValueError("Galileo queue directory must be a canonical non-link path")

    euid = os.geteuid() if hasattr(os, "geteuid") else os.stat(path).st_uid
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        info = os.lstat(current)
        mode = stat.S_IMODE(info.st_mode)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ValueError("Galileo queue path contains a link or non-directory")
        trusted_sticky = info.st_uid == 0 and bool(mode & stat.S_ISVTX)
        if info.st_uid not in {0, euid} or (
            mode & 0o022 and not trusted_sticky and current != path
        ):
            raise ValueError("Galileo queue path has an untrusted writable ancestor")

    final = os.lstat(path)
    if final.st_uid != euid or stat.S_IMODE(final.st_mode) != 0o700:
        raise ValueError("Galileo queue directory must be service-owned mode 0700")
    for root, directories, files in os.walk(path, followlinks=False):
        for name in directories:
            info = os.lstat(Path(root) / name)
            if (
                stat.S_ISLNK(info.st_mode)
                or not stat.S_ISDIR(info.st_mode)
                or info.st_uid != euid
                or stat.S_IMODE(info.st_mode) != 0o700
            ):
                raise ValueError("Galileo queue contains an unsafe directory")
        for name in files:
            info = os.lstat(Path(root) / name)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_uid != euid
                or stat.S_IMODE(info.st_mode) != 0o600
            ):
                raise ValueError(
                    "Galileo queue database files must be single-link mode 0600"
                )
    if shutil.disk_usage(path).free < MIN_QUEUE_FREE_BYTES:
        raise ValueError("Galileo queue filesystem lacks the required free capacity")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--print-destination-fingerprint",
        action="store_true",
        help="Print only the non-secret target fingerprint and exit",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    environment = dict(os.environ)
    endpoint_raw = environment.get("GALILEO_OTLP_TRACES_ENDPOINT", "")
    key_path_raw = environment.get("GALILEO_API_KEY_FILE", "")
    endpoint = endpoint_raw.strip()
    key_path = key_path_raw.strip()
    if not endpoint:
        raise SystemExit("ERROR: GALILEO_OTLP_TRACES_ENDPOINT is required")
    if not key_path and not args.print_destination_fingerprint:
        raise SystemExit("ERROR: GALILEO_API_KEY_FILE is required")
    if endpoint != endpoint_raw or (key_path and key_path != key_path_raw):
        raise SystemExit(
            "ERROR: Galileo endpoint and key-file path must not have outer whitespace"
        )
    if "GALILEO_API_KEY" in environment:
        raise SystemExit(
            "ERROR: remove inline GALILEO_API_KEY and use the protected key file"
        )
    try:
        endpoint_origin, canonical_endpoint = validate_endpoint(endpoint)
        validate_expected_origin(
            environment.get("GALILEO_EXPECTED_ORIGIN", ""), endpoint_origin
        )
        selector_pair = validate_selectors(environment)
        derived_fingerprint = destination_fingerprint(canonical_endpoint, selector_pair)
        if args.print_destination_fingerprint:
            print(derived_fingerprint)
            return
        declared_fingerprint = validate_declared_fingerprint(
            environment, derived_fingerprint
        )
        # Prove the local proxy's exact protected assets and live allow/deny
        # behavior before the Galileo secret is ever read into memory.
        validate_tinyproxy_contract(environment, canonical_endpoint)
        validate_queue_directory(
            environment.get("GALILEO_QUEUE_STORAGE_DIRECTORY", ""),
            declared_fingerprint,
        )
        api_key = read_secret(Path(key_path))
    except ValueError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc

    if args.check:
        print("Galileo collector runtime environment passed protected-file validation")
        return
    command = list(args.command)
    if command and command[0] == "--":
        command.pop(0)
    if not command:
        parser.error("a collector command is required after --")
    environment = restricted_transport_environment(environment)
    environment["GALILEO_API_KEY"] = api_key
    environment.pop("GALILEO_API_KEY_FILE", None)
    try:
        os.execvpe(command[0], command, environment)
    except Exception:
        raise SystemExit("ERROR: collector command could not be executed") from None


if __name__ == "__main__":
    main()
