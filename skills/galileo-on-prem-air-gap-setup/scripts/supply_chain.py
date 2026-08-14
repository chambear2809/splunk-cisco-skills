#!/usr/bin/env python3
"""Digest-bound Galileo air-gap renderer, verifier, and registry handoff builder."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import ipaddress
import json
import os
import re
import shutil
import stat
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import NoReturn
from urllib.parse import urlsplit, urlunsplit

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "skills" / "shared" / "lib"))
from yaml_compat import load_yaml_or_json  # noqa: E402

SCHEMA = "galileo-on-prem-air-gap-bundle/v1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
OCI_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
HOST = re.compile(
    r"^(?:\[[0-9a-fA-F:]+\]|[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?)(?::[0-9]{1,5})?$"
)
DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
USES = {"runtime", "init", "hook", "job", "test", "model"}
ARCHES = {"amd64", "arm64", "ppc64le", "s390x"}
OCI_INDEX_MEDIA_TYPES = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
}
OCI_MANIFEST_MEDIA_TYPES = {
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
}
OCI_LAYER_MEDIA_TYPES = {
    "application/vnd.oci.image.layer.v1.tar",
    "application/vnd.oci.image.layer.v1.tar+gzip",
    "application/vnd.oci.image.layer.v1.tar+zstd",
    "application/vnd.oci.image.layer.nondistributable.v1.tar",
    "application/vnd.oci.image.layer.nondistributable.v1.tar+gzip",
    "application/vnd.oci.image.layer.nondistributable.v1.tar+zstd",
    "application/vnd.docker.image.rootfs.diff.tar.gzip",
    "application/vnd.docker.image.rootfs.foreign.diff.tar.gzip",
}
PUBLIC_SUFFIXES = (
    "docker.io",
    "ghcr.io",
    "quay.io",
    "gcr.io",
    "pkg.dev",
    "amazonaws.com",
    "azurecr.io",
    "letsencrypt.org",
    "sendgrid.net",
    "sentry.io",
    "logz.io",
    "galileo.ai",
    "galileocloud.io",
    "huggingface.co",
    "openai.com",
)
REPOSITORY_SEGMENT = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
TAG = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
RELEASE_ID = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9])?$")
SECRET_PATH_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
IMAGE_LITERAL = re.compile(
    r"(?m)^\s*image\s*:\s*['\"]?([A-Za-z0-9.-]+(?::[0-9]+)?/[a-z0-9._/-]+:[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})['\"]?\s*$"
)
SENSITIVE_VALUE = re.compile(
    r"(?i)(?:bearer\s+\S+|(?:password|passwd|token|api[_-]?key|secret|credential)\s*[:=]\s*\S+|-----BEGIN [A-Z ]*PRIVATE KEY-----|https?://[^/@\s:]+:[^/@\s]+@)"
)
URL_LITERAL = re.compile(
    r"(?i)\b(?:https?|grpcs?|wss?|postgres(?:ql)?|redis|rediss|amqp|amqps|smtp|smtps|s3)://[^\s\"'<>]+"
)
ENDPOINT_SETTING = re.compile(
    r"(?im)\b(url|uri|dsn|endpoint|host|hostname|server|address)\b\s*[:=]\s*['\"]?([^\s'\"#,}]+)"
)
HELM_ACTION = re.compile(r"(?s){{-?(.*?)-?}}")
HELM_DYNAMIC_FUNCTION = re.compile(
    r"(?i)(?<![A-Za-z0-9_.])(?:"
    r"lookup|tpl|rand[A-Za-z0-9_]*|shuffle|uuidv4|now|ago|date|dateInZone|"
    r"dateModify|mustDateModify|htmlDate|htmlDateInZone|env|expandenv|"
    r"getHostByName|genPrivateKey|genCA|genCAWithKey|genSelfSignedCert|"
    r"genSelfSignedCertWithKey|genSignedCert|genSignedCertWithKey|encryptAES|"
    r"htpasswd|bcrypt|dig|pluck|call"
    r")(?=\s|\()"
)
HELM_FILES_ACCESS = re.compile(r"(?i)(?<![A-Za-z0-9_])\.Files\b")
HELM_RUNTIME_CONTEXT = re.compile(
    r"""(?i)(?:\.(?:Capabilities|Release)\b|["'](?:Capabilities|Release|Files)["'])"""
)
HELM_ROOT_ALIAS = re.compile(
    r"(?i)\$[A-Za-z_][A-Za-z0-9_]*\s*:?=\s*(?:\.|\$)(?=\s|[|)])"
)
HELM_ROOT_ACCESSOR = re.compile(r"(?i)(?<![A-Za-z0-9_.])(?:index|get)(?=\s|\()")
HELM_TEXT_SUFFIXES = {".yaml", ".yml", ".tpl", ".txt", ".json"}
WORKLOAD_KINDS = {
    "Deployment",
    "StatefulSet",
    "DaemonSet",
    "ReplicaSet",
    "Job",
    "CronJob",
    "Pod",
}


def fail(message: str) -> NoReturn:
    raise SystemExit(f"ERROR: {message}")


def valid_workload_object(value: str) -> bool:
    """Return whether ``Kind/name`` is an exact Kubernetes DNS-subdomain identity."""
    kind, separator, name = value.partition("/")
    return bool(
        separator
        and kind in WORKLOAD_KINDS
        and len(name) <= 253
        and all(DNS_LABEL.fullmatch(label) for label in name.split("."))
    )


@dataclass(frozen=True)
class Artifact:
    path: Path
    sha256: str
    size: int
    device: int
    inode: int
    mtime_ns: int
    ctime_ns: int
    data: bytes | None = None


def secure_file(
    raw: str | Path,
    label: str,
    *,
    private: bool = False,
    limit: int = 80 * 1024 * 1024 * 1024,
    load: bool = False,
) -> Artifact:
    candidate = Path(raw).expanduser()
    path = Path(
        os.path.abspath(
            candidate if candidate.is_absolute() else Path.cwd() / candidate
        )
    )
    cursor = path.parent
    while True:
        try:
            ancestor = os.lstat(cursor)
        except OSError:
            fail(f"{label} has an unavailable ancestor")
        if stat.S_ISLNK(ancestor.st_mode) or not stat.S_ISDIR(ancestor.st_mode):
            fail(f"{label} has a symlink/non-directory ancestor")
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    try:
        before = os.lstat(path)
    except OSError:
        fail(f"{label} is unavailable")
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISREG(before.st_mode)
        or before.st_uid != os.getuid()
        or before.st_nlink != 1
    ):
        fail(f"{label} must be current-user-owned, regular, and single-link")
    mode = stat.S_IMODE(before.st_mode)
    if (private and mode & 0o077) or (not private and mode & 0o022):
        fail(f"{label} has unsafe permissions")
    if before.st_size > limit:
        fail(f"{label} exceeds the size limit")
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        )
    except OSError:
        fail(f"{label} could not be opened safely")
    try:
        opened = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
            opened.st_ctime_ns,
        ):
            fail(f"{label} changed before read")
        digest = hashlib.sha256()
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(4 * 1024 * 1024, limit + 1 - total))
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
            if load:
                chunks.append(chunk)
            if total > limit:
                fail(f"{label} exceeds the size limit")
        final = os.fstat(descriptor)
        if (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
            opened.st_ctime_ns,
        ) != (
            final.st_dev,
            final.st_ino,
            final.st_size,
            final.st_mtime_ns,
            final.st_ctime_ns,
        ):
            fail(f"{label} changed during read")
    finally:
        os.close(descriptor)
    return Artifact(
        path,
        digest.hexdigest(),
        before.st_size,
        before.st_dev,
        before.st_ino,
        before.st_mtime_ns,
        before.st_ctime_ns,
        b"".join(chunks) if load else None,
    )


def secure_read(
    raw: str | Path, label: str, *, private: bool = False, limit: int = 16 * 1024 * 1024
) -> Artifact:
    return secure_file(raw, label, private=private, limit=limit, load=True)


def open_bound(artifact: Artifact, label: str) -> int:
    try:
        before = os.lstat(artifact.path)
    except OSError:
        fail(f"{label} disappeared")
    identity = (
        artifact.device,
        artifact.inode,
        artifact.size,
        artifact.mtime_ns,
        artifact.ctime_ns,
    )
    if (
        stat.S_ISLNK(before.st_mode)
        or (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        != identity
    ):
        fail(f"{label} changed after validation")
    try:
        descriptor = os.open(
            artifact.path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        )
    except OSError:
        fail(f"{label} could not be reopened safely")
    opened = os.fstat(descriptor)
    if (
        opened.st_dev,
        opened.st_ino,
        opened.st_size,
        opened.st_mtime_ns,
        opened.st_ctime_ns,
    ) != identity:
        os.close(descriptor)
        fail(f"{label} changed while opening")
    return descriptor


def artifact_bytes(
    artifact: Artifact, label: str, limit: int = 16 * 1024 * 1024
) -> bytes:
    if artifact.data is not None:
        return artifact.data
    if artifact.size > limit:
        fail(f"{label} is too large for structured parsing")
    descriptor = open_bound(artifact, label)
    try:
        data = b""
        while len(data) <= limit:
            chunk = os.read(descriptor, min(1024 * 1024, limit + 1 - len(data)))
            if not chunk:
                break
            data += chunk
        final = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        len(data) > limit
        or hashlib.sha256(data).hexdigest() != artifact.sha256
        or final.st_size != len(data)
    ):
        fail(f"{label} changed or exceeds its parsing bound")
    return data


def mapping(artifact: Artifact) -> dict:
    try:
        value = load_yaml_or_json(
            artifact_bytes(artifact, str(artifact.path)).decode(),
            source=str(artifact.path),
        )
    except UnicodeDecodeError:
        fail(f"{artifact.path} is not UTF-8")
    if not isinstance(value, dict):
        fail(f"{artifact.path} must contain a mapping")
    return value


def strict_json_mapping(
    artifact: Artifact, label: str, *, canonical: bool = False
) -> dict:
    """Parse an attestation as duplicate-free JSON, optionally canonical JSON."""

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict:
        result: dict = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate key: {key}")
            result[key] = value
        return result

    try:
        raw = artifact_bytes(artifact, label)
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        fail(f"{label} must be duplicate-free JSON")
    if not isinstance(document, dict):
        fail(f"{label} must contain an object")
    if canonical and raw != canonical_json(document):
        fail(f"{label} must be canonical JSON")
    return document


def checked(raw: str, expected: str, label: str, **kwargs: object) -> Artifact:
    artifact = secure_file(raw, label, **kwargs)
    if not HEX64.fullmatch(expected) or artifact.sha256 != expected:
        fail(f"{label} SHA-256 mismatch")
    return artifact


def only(value: dict, allowed: set[str], where: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        fail(f"unknown {where} field(s): {', '.join(unknown)}")


def text(value: dict, key: str, where: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip() or "CHANGE_ME" in result:
        fail(f"{where}.{key} must be resolved")
    result = result.strip()
    if SENSITIVE_VALUE.search(result):
        fail(f"{where}.{key} contains credential-shaped text")
    return result


def boolean(value: dict, key: str, where: str) -> bool:
    result = value.get(key)
    if not isinstance(result, bool):
        fail(f"{where}.{key} must be boolean")
    return result


def require_child_evidence_coverage(
    optional_components: dict[str, str], observed_components: set[str]
) -> None:
    expected = {
        component
        for component, ownership in optional_components.items()
        if ownership == "standalone"
    }
    if observed_components != expected:
        fail(
            "child image evidence must exactly cover every enabled standalone optional component"
        )


def origin(raw: str) -> str:
    parsed = urlsplit(raw.strip())
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        fail("Galileo console URL must be an HTTPS origin")
    try:
        port = parsed.port
    except ValueError:
        fail("Galileo console URL port is invalid")
    host = parsed.hostname.lower()
    netloc = f"[{host}]" if ":" in host else host
    if port:
        netloc += f":{port}"
    return urlunsplit(("https", netloc, "/", "", ""))


def endpoint_hostname(raw: str) -> str:
    value = raw.strip().lower()
    if value.startswith("["):
        close = value.find("]")
        return value[1:close] if close > 0 else value
    if value.count(":") == 1 and value.rsplit(":", 1)[1].isdigit():
        return value.rsplit(":", 1)[0]
    return value


def validate_hostport(raw: str, label: str) -> str:
    value = raw.strip().lower()
    if not HOST.fullmatch(value):
        fail(f"{label} must be an exact host or host:port")
    parsed = urlsplit("//" + value)
    try:
        port = parsed.port
    except ValueError:
        fail(f"{label} port is invalid")
    host = parsed.hostname.lower() if parsed.hostname else ""
    if not host or parsed.path or parsed.username or parsed.password:
        fail(f"{label} is invalid")
    try:
        address = ipaddress.ip_address(host)
        normalized_host = address.compressed.lower()
        display_host = (
            f"[{normalized_host}]" if address.version == 6 else normalized_host
        )
    except ValueError:
        if len(host) > 253 or any(
            not DNS_LABEL.fullmatch(part) for part in host.split(".")
        ):
            fail(f"{label} must use canonical DNS labels or an IP address")
        display_host = host
    if port is not None and not 1 <= port <= 65535:
        fail(f"{label} port is invalid")
    normalized = display_host + (f":{port}" if port is not None else "")
    if value != normalized:
        fail(f"{label} must use a canonical lowercase host[:port]")
    return normalized


def validate_dns_suffix(raw: str, label: str) -> str:
    value = raw.strip().lower().lstrip(".")
    if (
        value != raw.strip().lower()
        or len(value) > 253
        or "." not in value
        or any(not DNS_LABEL.fullmatch(part) for part in value.split("."))
    ):
        fail(f"{label} must be an exact canonical DNS suffix without wildcards")
    return value


def endpoint_literal_host(raw: str) -> str | None:
    """Return only normalized host[:port], never URL credentials/path/query."""
    candidate = raw.strip().rstrip(",.;)}]")
    if not candidate or "{{" in candidate or "${" in candidate:
        return None
    parsed = urlsplit(candidate if "://" in candidate else "//" + candidate)
    try:
        port = parsed.port
    except ValueError:
        return None
    if not parsed.hostname or (port is not None and not 1 <= port <= 65535):
        return None
    host = parsed.hostname.lower().rstrip(".")
    hostport = f"[{host}]" if ":" in host else host
    if port is not None:
        hostport += f":{port}"
    return hostport if HOST.fullmatch(hostport) else None


def endpoint_hosts_in_text(value: str) -> set[str]:
    hosts: set[str] = set()
    for candidate in URL_LITERAL.findall(value):
        host = endpoint_literal_host(candidate)
        if host:
            hosts.add(host)
    for _key, candidate in ENDPOINT_SETTING.findall(value):
        host = endpoint_literal_host(candidate)
        if host:
            hosts.add(host)
    return hosts


def static_endpoint_hosts(bundle: Path) -> set[str]:
    """Independently scan immutable nonsecret values and chart templates."""
    hosts: set[str] = set()

    def scan_dependency(payload: bytes, depth: int) -> None:
        if depth > 4:
            fail("bundled endpoint chart dependency nesting exceeds four levels")
        try:
            dependency = tarfile.open(fileobj=io.BytesIO(payload), mode="r:*")
        except tarfile.TarError:
            fail("bundled endpoint chart dependency is malformed")
        with dependency:
            members = dependency.getmembers()
            if not members or len(members) > 5000:
                fail("bundled endpoint chart dependency member count is invalid")
            for member in members:
                pure = normalized_member(member.name, "bundled endpoint dependency")
                if (
                    member.pax_headers
                    or member.issparse()
                    or not (member.isfile() or member.isdir())
                    or member.size > 64 * 1024 * 1024
                ):
                    fail("bundled endpoint chart dependency contains unsafe entries")
                if not member.isfile():
                    continue
                handle = dependency.extractfile(member)
                data = handle.read(64 * 1024 * 1024 + 1) if handle else b""
                if len(data) > 64 * 1024 * 1024:
                    fail("bundled endpoint chart dependency member is oversized")
                if pure.suffix == ".tgz" and "charts" in pure.parts:
                    scan_dependency(data, depth + 1)
                if (
                    pure.suffix not in {".yaml", ".yml", ".tpl"}
                    and "templates" not in pure.parts
                ):
                    continue
                try:
                    hosts.update(endpoint_hosts_in_text(data.decode("utf-8")))
                except UnicodeDecodeError:
                    continue

    values = bundle / "values"
    if values.is_dir() and not values.is_symlink():
        for path in sorted(values.iterdir()):
            if path.suffix.lower() not in {".yaml", ".yml", ".json"}:
                continue
            artifact = secure_read(path, "bundled nonsecret endpoint input")
            try:
                hosts.update(
                    endpoint_hosts_in_text(
                        artifact_bytes(
                            artifact, "bundled nonsecret endpoint input"
                        ).decode("utf-8")
                    )
                )
            except UnicodeDecodeError:
                fail("bundled nonsecret endpoint input is not UTF-8")
    artifacts_dir = bundle / "artifacts"
    if artifacts_dir.is_dir() and not artifacts_dir.is_symlink():
        for path in sorted(artifacts_dir.glob("*.tgz")):
            artifact = secure_file(
                path, "bundled endpoint chart", limit=512 * 1024 * 1024
            )
            descriptor, fileobj = bound_fileobj(artifact, "bundled endpoint chart")
            try:
                with tarfile.open(fileobj=fileobj, mode="r:*") as archive:
                    for member in archive.getmembers():
                        pure = normalized_member(member.name, "bundled endpoint chart")
                        normalized = pure.as_posix().lower()
                        if (
                            member.pax_headers
                            or member.issparse()
                            or not (member.isfile() or member.isdir())
                            or member.size > 64 * 1024 * 1024
                        ):
                            fail("bundled endpoint chart contains unsafe entries")
                        if not member.isfile():
                            continue
                        handle = archive.extractfile(member)
                        if handle is None:
                            fail("bundled chart endpoint member could not be read")
                        if pure.suffix == ".tgz" and "charts" in pure.parts:
                            if member.size > 64 * 1024 * 1024:
                                fail("bundled endpoint chart dependency is oversized")
                            scan_dependency(handle.read(64 * 1024 * 1024 + 1), 1)
                            continue
                        if member.size > 4 * 1024 * 1024 or not (
                            "/templates/" in normalized
                            or normalized.endswith("/values.yaml")
                            or normalized.endswith("/values.yml")
                        ):
                            continue
                        try:
                            hosts.update(
                                endpoint_hosts_in_text(handle.read().decode("utf-8"))
                            )
                        except UnicodeDecodeError:
                            continue
            except (tarfile.TarError, OSError):
                fail("bundled endpoint chart could not be inspected")
            finally:
                try:
                    fileobj.close()
                finally:
                    finish_bound(descriptor, artifact, "bundled endpoint chart")
    return hosts


def normalize_endpoint_rows(rows: object, label: str) -> list[dict]:
    if not isinstance(rows, list):
        fail(f"{label} items must be a list")
    normalized: list[dict] = []
    identities: set[tuple[str, str, str]] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != {"host", "purpose", "source"}:
            fail(f"{label} row {index} is invalid")
        host = validate_hostport(text(row, "host", f"{label}[{index}]"), label)
        purpose = text(row, "purpose", f"{label}[{index}]")
        source = text(row, "source", f"{label}[{index}]")
        if (
            len(purpose) > 256
            or len(source) > 512
            or SENSITIVE_VALUE.search(purpose)
            or SENSITIVE_VALUE.search(source)
            or any(ord(character) < 32 for character in purpose + source)
        ):
            fail(f"{label} row {index} contains unsafe human text")
        identity = (host, purpose, source)
        if identity in identities:
            fail(f"{label} contains duplicate rows")
        identities.add(identity)
        normalized.append({"host": host, "purpose": purpose, "source": source})
    expected = sorted(
        normalized, key=lambda item: (item["host"], item["purpose"], item["source"])
    )
    if rows != expected:
        fail(f"{label} rows are not canonical")
    return expected


def bind_rendered_mirrors(
    images: list[dict],
    rendered: dict[str, set[str]],
    label: str,
) -> dict[str, set[str]]:
    """Bind final rendered private refs to vendor acquisitions by exact digest."""
    mirror_map = {item["mirror"]: item for item in images}
    if set(rendered) != set(mirror_map):
        fail(f"{label} must exactly equal the private mirror reference set")
    owners_by_source: dict[str, set[str]] = {}
    for mirror, owners in rendered.items():
        item = mirror_map[mirror]
        if item["mirror_digest"] != item["source_digest"]:
            fail(f"{label} mirror/source digest provenance differs")
        owners_by_source.setdefault(item["source"], set()).update(owners)
    return owners_by_source


def normalize_rendered_image_rows(
    rows: object, release_owners: dict[str, str], label: str
) -> tuple[set[str], dict[str, set[str]]]:
    if not isinstance(rows, list) or not rows:
        fail(f"{label} must contain a non-empty item list")
    identities: set[tuple[str, str, str, str]] = set()
    sources: set[str] = set()
    owners: dict[str, set[str]] = {}
    normalized: list[dict] = []
    for index, row in enumerate(rows):
        where = f"{label}[{index}]"
        if not isinstance(row, dict) or set(row) != {
            "release",
            "source_object",
            "container_type",
            "container",
            "image",
            "digest",
            "eligible_architectures",
        }:
            fail(f"{where} has a malformed closed schema")
        release = text(row, "release", where)
        source_object = text(row, "source_object", where)
        container_type = text(row, "container_type", where)
        container = text(row, "container", where)
        image = text(row, "image", where)
        digest = text(row, "digest", where)
        eligible = row.get("eligible_architectures")
        if (
            release not in release_owners
            or not valid_workload_object(source_object)
            or container_type
            not in {"container", "initContainer", "ephemeralContainer"}
            or not DNS_LABEL.fullmatch(container)
            or not OCI_DIGEST.fullmatch(digest)
            or not image.endswith("@" + digest)
            or not isinstance(eligible, list)
            or not eligible
            or any(not isinstance(value, str) for value in eligible)
            or eligible != sorted(set(eligible))
            or not set(eligible) <= ARCHES
        ):
            fail(f"{where} has invalid object/container/image identity")
        source = image_reference(image.rsplit("@", 1)[0], f"{where}.image")
        if image != f"{source}@{digest}":
            fail(f"{where}.image is not canonical")
        identity = (release, source_object, container_type, container)
        if identity in identities:
            fail(f"{label} contains duplicate workload/container identities")
        identities.add(identity)
        sources.add(source)
        owners.setdefault(source, set()).add(release_owners[release])
        normalized.append(dict(row))
    expected = sorted(
        normalized,
        key=lambda item: (
            item["release"],
            item["source_object"],
            item["container_type"],
            item["container"],
            item["image"],
        ),
    )
    if rows != expected:
        fail(f"{label} rows are not in canonical order")
    return sources, owners


def normalize_secret_input_contract(value: object, label: str) -> dict:
    """Validate a value-free secret path/type/influence contract."""
    if not isinstance(value, dict) or set(value) != {
        "schema",
        "path_policy",
        "leaves",
    }:
        fail(f"{label} has a malformed closed schema")
    leaves = value.get("leaves")
    if (
        value.get("schema") != "galileo-on-prem-redacted-secret-input-contract/v1"
        or value.get("path_policy") != "safe-helm-values-paths/v1"
        or not isinstance(leaves, list)
        or not leaves
    ):
        fail(f"{label} is invalid")
    paths: set[str] = set()
    normalized: list[dict] = []
    for index, leaf in enumerate(leaves):
        if not isinstance(leaf, dict) or set(leaf) != {
            "path",
            "shape",
            "influence",
        }:
            fail(f"{label}.leaves[{index}] has a malformed closed schema")
        path = leaf.get("path")
        shape = leaf.get("shape")
        influence = leaf.get("influence")
        if (
            not isinstance(path, str)
            or not path.startswith("/")
            or not path[1:]
            or path in paths
            or any(
                not SECRET_PATH_SEGMENT.fullmatch(part) for part in path[1:].split("/")
            )
            or shape
            not in {"string", "integer", "number", "boolean", "null", "object", "list"}
            or influence != ["helm-template", "kubernetes-server-dry-run"]
        ):
            fail(f"{label}.leaves[{index}] is invalid")
        paths.add(path)
        normalized.append(dict(leaf))
    if normalized != sorted(normalized, key=lambda item: item["path"]):
        fail(f"{label} leaves are not in canonical order")
    return {
        "schema": "galileo-on-prem-redacted-secret-input-contract/v1",
        "path_policy": "safe-helm-values-paths/v1",
        "leaves": normalized,
    }


def require_image_architecture_coverage(
    evidence_documents: list[dict], images: list[dict], target_arches: set[str]
) -> None:
    """Bind every exact rendered workload to its eligible node architectures."""
    mirrors = {item["mirror"]: item for item in images}
    observed: set[str] = set()
    for document in evidence_documents:
        rows = document.get("items") if isinstance(document, dict) else None
        if not isinstance(rows, list):
            fail("rendered image evidence lacks architecture-bound rows")
        for index, row in enumerate(rows):
            if not isinstance(row, dict) or not isinstance(row.get("image"), str):
                fail("rendered image architecture row is malformed")
            mirror = row["image"].rsplit("@", 1)[0]
            image = mirrors.get(mirror)
            eligible = row.get("eligible_architectures")
            if (
                image is None
                or not isinstance(eligible, list)
                or not eligible
                or any(not isinstance(value, str) for value in eligible)
                or eligible != sorted(set(eligible))
                or not set(eligible) <= target_arches
                or not set(eligible) <= set(image["architectures"])
            ):
                fail(
                    f"rendered image row {index} is not covered on every eligible node architecture"
                )
            observed.add(mirror)
    if observed != set(mirrors):
        fail("architecture evidence does not exactly cover the rendered mirror set")


def validate_source_mirror_roles(
    source: str, mirror: str, destination: str, label: str
) -> None:
    """Keep vendor acquisition and internal deployment identities distinct."""
    source_registry = source.split("/", 1)[0]
    mirror_registry = mirror.split("/", 1)[0]
    if (
        source == mirror
        or source_registry == mirror_registry
        or source.startswith(destination + "/")
        or not mirror.startswith(destination + "/")
    ):
        fail(f"{label} must use distinct vendor-source and internal-mirror registries")


def reject_dynamic_helm(body: bytes, label: str) -> None:
    """Reject server-dependent/dynamic template evaluation in offline evidence."""
    try:
        source = body.decode("utf-8")
    except UnicodeDecodeError:
        return
    for match in HELM_ACTION.finditer(source):
        action = match.group(1)
        if (
            HELM_DYNAMIC_FUNCTION.search(action)
            or HELM_FILES_ACCESS.search(action)
            or HELM_RUNTIME_CONTEXT.search(action)
            or HELM_ROOT_ALIAS.search(action)
            or HELM_ROOT_ACCESSOR.search(action)
        ):
            fail(
                f"{label} uses nondeterministic, runtime-context, network, environment, tpl, or .Files access; exact offline evidence cannot be proven"
            )


def public_endpoint(raw: str) -> bool:
    host = endpoint_hostname(raw)
    try:
        address = ipaddress.ip_address(host)
        return not (address.is_private or address.is_loopback or address.is_link_local)
    except ValueError:
        return True


def internal_hostname(raw: str, exact_hosts: set[str], suffixes: set[str]) -> bool:
    host = endpoint_hostname(raw)
    try:
        address = ipaddress.ip_address(host)
        return address.is_private or address.is_loopback or address.is_link_local
    except ValueError:
        return host in exact_hosts or any(
            host.endswith("." + suffix) for suffix in suffixes
        )


def require_exact_endpoint_closure(
    allowed: set[str],
    runtime: set[str],
    registry_host: str,
    exact_hosts: set[str],
    suffixes: set[str],
) -> None:
    """Require a closed internal allowlist for the exact rendered endpoint union."""
    expected = set(runtime) | {registry_host}
    if allowed != expected:
        fail(
            "no-egress allowlist must exactly equal rendered endpoints plus the private registry"
        )
    if any(not internal_hostname(value, exact_hosts, suffixes) for value in allowed):
        fail("no-egress closure contains a public or unclassified endpoint")


def registry(
    raw: str, exact_hosts: set[str] | None = None, suffixes: set[str] | None = None
) -> str:
    value = raw.strip().strip("/")
    if "://" in value or "/" not in value:
        fail(
            "registry.destination must be host[:port]/repository-prefix without a scheme"
        )
    host, repository = value.split("/", 1)
    host = validate_hostport(host, "registry.destination host")
    segments = repository.split("/")
    if any(not REPOSITORY_SEGMENT.fullmatch(segment) for segment in segments):
        fail("registry.destination repository path is invalid")
    registry_hostname = endpoint_hostname(host)
    if (
        exact_hosts is not None
        and suffixes is not None
        and not (
            registry_hostname in exact_hosts
            or any(registry_hostname.endswith("." + suffix) for suffix in suffixes)
        )
    ):
        fail(
            "registry.destination is not covered by the explicit internal host/suffix policy"
        )
    return f"{host}/{repository}"


def image_reference(raw: str, label: str) -> str:
    value = raw.strip()
    if "://" in value or "@" in value or "/" not in value:
        fail(f"{label} must be an explicit tagged OCI reference")
    name, separator, tag = value.rpartition(":")
    if (
        not separator
        or not TAG.fullmatch(tag)
        or tag.lower() == "latest"
        or "/" not in name
    ):
        fail(f"{label} must use a non-latest explicit tag")
    host, repository = name.split("/", 1)
    if validate_hostport(host, f"{label} registry") != host:
        fail(f"{label} registry must be canonical lowercase host[:port]")
    if any(
        not REPOSITORY_SEGMENT.fullmatch(segment) for segment in repository.split("/")
    ):
        fail(f"{label} repository path is invalid")
    return value


def timestamp(raw: object, label: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        fail(f"{label} must be an RFC3339 timestamp")
    value = raw.strip()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        fail(f"{label} must be an RFC3339 timestamp")
    if parsed.tzinfo is None or parsed > datetime.now(timezone.utc):
        fail(f"{label} must be timezone-aware and not in the future")
    return value


def normalized_member(raw: str, label: str) -> PurePosixPath:
    if "\\" in raw or "//" in raw or raw.startswith("./") or raw.endswith("/."):
        fail(f"{label} contains a non-canonical member path")
    pure = PurePosixPath(raw)
    if (
        pure.is_absolute()
        or ".." in pure.parts
        or "." in pure.parts
        or not pure.parts
        or len(raw) > 1024
    ):
        fail(f"{label} contains an unsafe member path")
    return pure


def bound_fileobj(artifact: Artifact, label: str) -> tuple[int, object]:
    descriptor = open_bound(artifact, label)
    return descriptor, os.fdopen(os.dup(descriptor), "rb", closefd=True)


def finish_bound(descriptor: int, artifact: Artifact, label: str) -> None:
    final = os.fstat(descriptor)
    os.close(descriptor)
    if (
        final.st_dev,
        final.st_ino,
        final.st_size,
        final.st_mtime_ns,
        final.st_ctime_ns,
    ) != (
        artifact.device,
        artifact.inode,
        artifact.size,
        artifact.mtime_ns,
        artifact.ctime_ns,
    ):
        fail(f"{label} changed during inspection")


def safe_archive(artifact: Artifact, label: str) -> dict:
    names: set[str] = set()
    roots: set[str] = set()
    total = 0
    count = 0

    def accept(name: str, size: int, entry_type: str, pax: bool = False) -> None:
        nonlocal total, count
        pure = normalized_member(name, label)
        canonical = pure.as_posix()
        if canonical in names:
            fail(f"{label} has duplicate paths")
        if pax or entry_type not in {"file", "dir"}:
            fail(f"{label} has links, sparse/special entries, or PAX overrides")
        if size > 8 * 1024 * 1024 * 1024:
            fail(f"{label} contains an oversized member")
        names.add(canonical)
        roots.add(pure.parts[0])
        total += size
        count += 1
        if count > 200000 or total > 64 * 1024 * 1024 * 1024:
            fail(f"{label} exceeds extraction bounds")

    descriptor, fileobj = bound_fileobj(artifact, label)
    try:
        try:
            context = tarfile.open(fileobj=fileobj, mode="r:*")
        except tarfile.TarError:
            context = None
        if context is not None:
            with context as archive:
                if archive.pax_headers:
                    fail(f"{label} has global PAX overrides")
                for item in archive.getmembers():
                    accept(
                        item.name,
                        item.size,
                        "file" if item.isfile() else "dir" if item.isdir() else "other",
                        bool(item.pax_headers) or item.issparse(),
                    )
        else:
            fileobj.seek(0)
            if not zipfile.is_zipfile(fileobj):
                return {
                    "type": "opaque",
                    "members": 1,
                    "expanded_bytes": artifact.size,
                    "roots": [],
                }
            fileobj.seek(0)
            with zipfile.ZipFile(fileobj) as archive:
                for item in archive.infolist():
                    mode = item.external_attr >> 16
                    entry_type = "dir" if item.is_dir() else "file"
                    if stat.S_ISLNK(mode):
                        entry_type = "other"
                    accept(item.filename, item.file_size, entry_type)
    finally:
        try:
            fileobj.close()
        finally:
            finish_bound(descriptor, artifact, label)
    if not names:
        fail(f"{label} is empty")
    if len(roots) != 1:
        fail(f"{label} must contain exactly one archive root")
    return {
        "type": "archive",
        "members": count,
        "expanded_bytes": total,
        "roots": sorted(roots),
    }


def oci_identity(artifact: Artifact) -> dict:
    """Verify a closed OCI descriptor graph and return its exact platform set."""
    blobs: dict[str, dict] = {}
    index = None
    layout = None
    descriptor, fileobj = bound_fileobj(artifact, "OCI archive")
    try:
        context = tarfile.open(fileobj=fileobj, mode="r:*")
    except tarfile.TarError:
        fileobj.close()
        finish_bound(descriptor, artifact, "OCI archive")
        fail("OCI archive must be a tar archive")
    seen: set[str] = set()
    total = 0
    try:
        with context as archive:
            if archive.pax_headers:
                fail("OCI archive has global PAX overrides")
            members = archive.getmembers()
            if not members or len(members) > 100000:
                fail("OCI archive member count is invalid")
            for member in members:
                pure = normalized_member(member.name, "OCI archive")
                canonical = pure.as_posix()
                if (
                    canonical in seen
                    or member.pax_headers
                    or not (member.isfile() or member.isdir())
                    or member.issparse()
                ):
                    fail("OCI archive has unsafe members")
                seen.add(canonical)
                total += member.size
                if (
                    member.size > 16 * 1024 * 1024 * 1024
                    or total > 64 * 1024 * 1024 * 1024
                ):
                    fail("OCI archive exceeds bounds")
                if not member.isfile():
                    if canonical not in {"blobs", "blobs/sha256"}:
                        fail("OCI archive contains an unexpected directory")
                    continue
                if canonical not in {"oci-layout", "index.json"} and not (
                    len(pure.parts) == 3
                    and pure.parts[:2] == ("blobs", "sha256")
                    and HEX64.fullmatch(pure.parts[2])
                ):
                    fail("OCI archive contains an unexpected file")
                handle = archive.extractfile(member)
                if handle is None:
                    fail("OCI member could not be read")
                digest = hashlib.sha256()
                retained = bytearray() if member.size <= 16 * 1024 * 1024 else None
                size = 0
                while True:
                    chunk = handle.read(4 * 1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    size += len(chunk)
                    if retained is not None:
                        retained.extend(chunk)
                if size != member.size:
                    fail("OCI member size changed during inspection")
                data = bytes(retained) if retained is not None else None
                if canonical == "oci-layout":
                    layout = data
                elif canonical == "index.json":
                    index = data
                elif len(pure.parts) == 3 and pure.parts[:2] == ("blobs", "sha256"):
                    if (
                        not HEX64.fullmatch(pure.parts[2])
                        or digest.hexdigest() != pure.parts[2]
                    ):
                        fail("OCI blob digest mismatch")
                    blobs[f"sha256:{pure.parts[2]}"] = {"size": size, "data": data}
    finally:
        try:
            fileobj.close()
        finally:
            finish_bound(descriptor, artifact, "OCI archive")
    if layout is None or index is None:
        fail("OCI archive lacks bounded oci-layout or index.json")

    def json_object(data: bytes, label: str) -> dict:
        def reject_duplicates(pairs: list[tuple[str, object]]) -> dict:
            result: dict = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"duplicate key: {key}")
                result[key] = value
            return result

        try:
            value = json.loads(
                data.decode("utf-8"), object_pairs_hook=reject_duplicates
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            fail(f"{label} must be duplicate-free UTF-8 JSON")
        if not isinstance(value, dict):
            fail(f"{label} must contain a JSON object")
        return value

    layout_doc = json_object(layout, "OCI layout")
    index_doc = json_object(index, "OCI root index")
    if layout_doc != {"imageLayoutVersion": "1.0.0"}:
        fail("unsupported or extended OCI layout version contract")
    manifests: set[str] = set()
    arches: set[str] = set()
    referenced: set[str] = set()
    referenced_media: dict[str, str] = {}
    content_references: set[str] = set()
    leaf_platforms: set[tuple[str, str, str | None]] = set()

    def annotations(value: object, label: str) -> None:
        if not isinstance(value, dict) or any(
            not isinstance(key, str) or not isinstance(item, str)
            for key, item in value.items()
        ):
            fail(f"{label} annotations must be a string mapping")

    def descriptor_blob(
        descriptor: dict,
        label: str,
        allowed_media_types: set[str],
        *,
        allow_platform: bool,
    ) -> tuple[str, str, bytes | None]:
        allowed = {"mediaType", "digest", "size", "annotations"}
        if allow_platform:
            allowed.add("platform")
        if set(descriptor) - allowed:
            fail(f"{label} contains unsupported descriptor fields")
        media = descriptor.get("mediaType")
        digest = descriptor.get("digest")
        size = descriptor.get("size")
        if (
            not isinstance(media, str)
            or media not in allowed_media_types
            or not isinstance(digest, str)
            or not OCI_DIGEST.fullmatch(digest)
            or digest not in blobs
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or size != blobs[digest]["size"]
        ):
            fail(f"{label} mediaType/digest/size closure is invalid")
        if "annotations" in descriptor:
            annotations(descriptor["annotations"], label)
        previous_media = referenced_media.setdefault(digest, media)
        if previous_media != media:
            fail("OCI blob digest is referenced with conflicting mediaTypes")
        referenced.add(digest)
        return digest, media, blobs[digest]["data"]

    def platform(value: object, label: str) -> tuple[str, str, str | None]:
        if not isinstance(value, dict) or set(value) not in (
            {"os", "architecture"},
            {"os", "architecture", "variant"},
        ):
            fail(f"{label} must contain exact os/architecture[/variant] fields")
        operating_system = value.get("os")
        architecture = value.get("architecture")
        variant = value.get("variant")
        has_variant = "variant" in value
        if (
            operating_system != "linux"
            or not isinstance(architecture, str)
            or architecture not in ARCHES
            or (
                has_variant
                and (
                    not isinstance(variant, str)
                    or not re.fullmatch(
                        r"v[0-9]+(?:\.[0-9]+)?(?:,[a-z0-9][a-z0-9_.+-]*)*",
                        variant,
                    )
                )
            )
            or (architecture in {"ppc64le", "s390x"} and has_variant)
        ):
            fail(f"{label} contains an unknown or unsupported platform")
        return operating_system, architecture, variant

    def document_header(
        document: dict,
        label: str,
        expected_media: str | None,
        allowed_media_types: set[str],
        required_fields: set[str],
        optional_fields: set[str],
    ) -> str | None:
        if (
            set(document) - required_fields - optional_fields
            or not required_fields <= set(document)
            or type(document.get("schemaVersion")) is not int
            or document.get("schemaVersion") != 2
        ):
            fail(f"{label} has an unsupported closed schema")
        media = document.get("mediaType")
        if expected_media is None:
            if media is not None and media not in allowed_media_types:
                fail(f"{label} mediaType is unsupported")
        elif media != expected_media:
            fail(f"{label} mediaType differs from its descriptor")
        if "annotations" in document:
            annotations(document["annotations"], label)
        return media if isinstance(media, str) else None

    def visit_manifest(
        descriptor: dict, label: str, declared_platform: object | None
    ) -> tuple[str, str, str | None]:
        digest, media, data = descriptor_blob(
            descriptor,
            label,
            OCI_MANIFEST_MEDIA_TYPES,
            allow_platform=True,
        )
        if digest in content_references:
            fail("OCI manifest/index descriptors are duplicated")
        content_references.add(digest)
        if data is None:
            fail("OCI image manifest JSON exceeds 16 MiB")
        manifest = json_object(data, "OCI image manifest")
        document_header(
            manifest,
            "OCI image manifest",
            media,
            OCI_MANIFEST_MEDIA_TYPES,
            {"schemaVersion", "mediaType", "config", "layers"},
            {"annotations"},
        )
        config = manifest.get("config")
        if not isinstance(config, dict):
            fail("OCI image manifest lacks a config descriptor")
        expected_config_media = (
            {"application/vnd.oci.image.config.v1+json"}
            if media == "application/vnd.oci.image.manifest.v1+json"
            else {"application/vnd.docker.container.image.v1+json"}
        )
        expected_layer_media = (
            {
                value
                for value in OCI_LAYER_MEDIA_TYPES
                if value.startswith("application/vnd.oci.")
            }
            if media == "application/vnd.oci.image.manifest.v1+json"
            else {
                value
                for value in OCI_LAYER_MEDIA_TYPES
                if value.startswith("application/vnd.docker.")
            }
        )
        config_digest, _config_media, config_data = descriptor_blob(
            config,
            "OCI config descriptor",
            expected_config_media,
            allow_platform=False,
        )
        if config_data is None:
            fail("OCI image config JSON exceeds 16 MiB")
        config_doc = json_object(config_data, "OCI image config")
        config_platform = platform(
            {
                "os": config_doc.get("os"),
                "architecture": config_doc.get("architecture"),
                **(
                    {"variant": config_doc["variant"]}
                    if "variant" in config_doc
                    else {}
                ),
            },
            "OCI image config platform",
        )
        if (
            declared_platform is not None
            and platform(declared_platform, f"{label} platform") != config_platform
        ):
            fail("OCI descriptor platform differs from referenced config platform")
        layers = manifest.get("layers")
        if not isinstance(layers, list):
            fail("OCI image manifest layers are invalid")
        rootfs = config_doc.get("rootfs")
        diff_ids = rootfs.get("diff_ids") if isinstance(rootfs, dict) else None
        if (
            not isinstance(rootfs, dict)
            or set(rootfs) != {"type", "diff_ids"}
            or rootfs.get("type") != "layers"
            or not isinstance(diff_ids, list)
            or len(diff_ids) != len(layers)
            or any(
                not isinstance(diff_id, str) or not OCI_DIGEST.fullmatch(diff_id)
                for diff_id in diff_ids
            )
        ):
            fail("OCI image config rootfs does not bind the manifest layer count")
        layer_digests: set[str] = set()
        for index, layer in enumerate(layers):
            if not isinstance(layer, dict):
                fail("OCI layer descriptor is malformed")
            layer_digest, _layer_media, _layer_data = descriptor_blob(
                layer,
                f"OCI layer descriptor {index}",
                expected_layer_media,
                allow_platform=False,
            )
            if layer_digest in layer_digests or layer_digest == config_digest:
                fail("OCI manifest contains duplicate config/layer descriptors")
            layer_digests.add(layer_digest)
        manifests.add(digest)
        if config_platform in leaf_platforms:
            fail("OCI archive contains duplicate image platform manifests")
        leaf_platforms.add(config_platform)
        arches.add(config_platform[1])
        return config_platform

    def visit_index(
        descriptor: dict, label: str, depth: int
    ) -> set[tuple[str, str, str | None]]:
        if depth > 8:
            fail("OCI nested index depth exceeds eight levels")
        digest, media, data = descriptor_blob(
            descriptor,
            label,
            OCI_INDEX_MEDIA_TYPES,
            allow_platform=True,
        )
        if digest in content_references:
            fail("OCI manifest/index descriptors are duplicated")
        content_references.add(digest)
        if data is None:
            fail("OCI image index JSON exceeds 16 MiB")
        nested = json_object(data, "OCI nested index")
        document_header(
            nested,
            "OCI nested index",
            media,
            OCI_INDEX_MEDIA_TYPES,
            {"schemaVersion", "mediaType", "manifests"},
            {"annotations"},
        )
        children = nested.get("manifests")
        if not isinstance(children, list) or not children:
            fail("OCI nested index has no image descriptors")
        child_digests: set[str] = set()
        result: set[tuple[str, str, str | None]] = set()
        for index, child in enumerate(children):
            if not isinstance(child, dict):
                fail("OCI child descriptor is malformed")
            child_digest = child.get("digest")
            if not isinstance(child_digest, str) or child_digest in child_digests:
                fail("OCI nested index contains duplicate descriptors")
            child_digests.add(child_digest)
            child_media = child.get("mediaType")
            if child_media in OCI_MANIFEST_MEDIA_TYPES:
                if "platform" not in child:
                    fail("OCI index image descriptor is missing its platform")
                result.add(
                    visit_manifest(
                        child,
                        f"OCI nested index manifest descriptor {index}",
                        child["platform"],
                    )
                )
            elif child_media in OCI_INDEX_MEDIA_TYPES:
                child_platforms = visit_index(
                    child, f"OCI nested index descriptor {index}", depth + 1
                )
                if "platform" in child:
                    declared = platform(
                        child["platform"],
                        f"OCI nested index descriptor {index} platform",
                    )
                    if child_platforms != {declared}:
                        fail(
                            "OCI nested index platform differs from its leaf config platforms"
                        )
                result.update(child_platforms)
            else:
                fail("OCI nested index descriptor mediaType is unsupported")
        return result

    roots = index_doc.get("manifests", [])
    document_header(
        index_doc,
        "OCI root index",
        None,
        OCI_INDEX_MEDIA_TYPES,
        {"schemaVersion", "manifests"},
        {"mediaType", "annotations"},
    )
    if not isinstance(roots, list) or len(roots) != 1:
        fail("OCI archive must contain exactly one root descriptor")
    root_digest = roots[0].get("digest") if isinstance(roots[0], dict) else None
    descriptor = roots[0]
    if not isinstance(descriptor, dict):
        fail("OCI root descriptor is malformed")
    media = descriptor.get("mediaType")
    if media in OCI_MANIFEST_MEDIA_TYPES:
        # A single-platform layout may omit the redundant descriptor platform;
        # its identity is derived exclusively from the verified config object.
        visit_manifest(
            descriptor, "OCI root manifest descriptor", descriptor.get("platform")
        )
    elif media in OCI_INDEX_MEDIA_TYPES:
        root_platforms = visit_index(descriptor, "OCI root index descriptor", 1)
        if "platform" in descriptor:
            declared = platform(descriptor["platform"], "OCI root index platform")
            if root_platforms != {declared}:
                fail("OCI root index platform differs from its leaf config platforms")
    else:
        fail("OCI root descriptor mediaType is unsupported")
    if (
        not manifests
        or not isinstance(root_digest, str)
        or not OCI_DIGEST.fullmatch(root_digest)
    ):
        fail("OCI archive contains no valid image manifests")
    if set(blobs) != referenced or not arches or not arches <= ARCHES:
        fail("OCI archive contains unreferenced blobs or invalid architecture evidence")
    return {
        "root_digest": root_digest,
        "manifest_digests": sorted(manifests),
        "architectures": sorted(arches),
    }


SAFE_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?$")
SAFE_VERSION = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._+-]{0,126})$")


def inspect_helm_chart(
    artifact: Artifact, expected_name: str, expected_version: str
) -> dict:
    if not SAFE_NAME.fullmatch(expected_name) or not SAFE_VERSION.fullmatch(
        expected_version
    ):
        fail("Helm chart name/version is unsafe")
    descriptor, fileobj = bound_fileobj(artifact, f"Helm chart {expected_name}")
    try:
        context = tarfile.open(fileobj=fileobj, mode="r:*")
    except tarfile.TarError:
        fileobj.close()
        finish_bound(descriptor, artifact, f"Helm chart {expected_name}")
        fail(f"Helm chart {expected_name} is malformed")
    seen: set[str] = set()
    roots: set[str] = set()
    total = 0
    chart_docs: list[bytes] = []
    declared_images: set[str] = set()

    def scan_dependency(payload: bytes, prefix: str, depth: int) -> None:
        if depth > 4:
            fail(f"Helm chart {expected_name} dependency nesting exceeds four levels")
        try:
            dependency = tarfile.open(fileobj=io.BytesIO(payload), mode="r:*")
        except tarfile.TarError:
            fail(f"Helm chart {expected_name} dependency is malformed")
        with dependency:
            members = dependency.getmembers()
            if not members or len(members) > 5000:
                fail(f"Helm chart {expected_name} dependency member count is invalid")
            seen_nested: set[str] = set()
            roots_nested: set[str] = set()
            chart_count = 0
            expanded = 0
            for nested in members:
                pure_nested = normalized_member(
                    nested.name, f"Helm chart {expected_name} dependency"
                )
                canonical_nested = pure_nested.as_posix()
                if canonical_nested in seen_nested:
                    fail(f"Helm chart {expected_name} dependency has duplicate members")
                seen_nested.add(canonical_nested)
                roots_nested.add(pure_nested.parts[0])
                if (
                    nested.pax_headers
                    or nested.issparse()
                    or not (nested.isfile() or nested.isdir())
                ):
                    fail(f"Helm chart {expected_name} dependency has unsafe entries")
                expanded += nested.size
                if nested.size > 64 * 1024 * 1024 or expanded > 128 * 1024 * 1024:
                    fail(f"Helm chart {expected_name} dependency exceeds bounds")
                if not nested.isfile():
                    continue
                handle = dependency.extractfile(nested)
                data = handle.read(64 * 1024 * 1024 + 1) if handle else b""
                if len(data) > 64 * 1024 * 1024:
                    fail(f"Helm chart {expected_name} dependency member is oversized")
                if len(pure_nested.parts) == 2 and pure_nested.name == "Chart.yaml":
                    chart_count += 1
                if pure_nested.suffix == ".tgz" and "charts" in pure_nested.parts:
                    scan_dependency(data, f"{prefix}!{nested.name}", depth + 1)
                if pure_nested.suffix.lower() in HELM_TEXT_SUFFIXES:
                    if len(data) > 4 * 1024 * 1024:
                        fail(
                            f"Helm chart {expected_name} dependency text member is oversized"
                        )
                    reject_dynamic_helm(
                        data,
                        f"Helm chart {expected_name} dependency {prefix}!{nested.name}",
                    )
                elif "templates" in pure_nested.parts:
                    if len(data) > 4 * 1024 * 1024:
                        fail(
                            f"Helm chart {expected_name} dependency template is oversized"
                        )
                    reject_dynamic_helm(
                        data,
                        f"Helm chart {expected_name} dependency {prefix}!{nested.name}",
                    )
                if (
                    pure_nested.suffix not in {".yaml", ".yml", ".tpl"}
                    and "templates" not in pure_nested.parts
                ):
                    continue
                try:
                    source = data.decode("utf-8")
                except UnicodeDecodeError:
                    source = ""
                for match in IMAGE_LITERAL.finditer(source):
                    declared_images.add(
                        image_reference(
                            match.group(1), "dependency chart image literal"
                        )
                    )
            if len(roots_nested) != 1 or chart_count != 1:
                fail(
                    f"Helm chart {expected_name} dependency must have one root Chart.yaml"
                )

    try:
        with context as archive:
            members = archive.getmembers()
            if not members or len(members) > 10000:
                fail(f"Helm chart {expected_name} has invalid member count")
            for member in members:
                pure = normalized_member(member.name, f"Helm chart {expected_name}")
                canonical = pure.as_posix()
                if canonical in seen:
                    fail(f"Helm chart {expected_name} has duplicate members")
                seen.add(canonical)
                roots.add(pure.parts[0])
                if (
                    member.pax_headers
                    or member.issparse()
                    or not (member.isfile() or member.isdir())
                ):
                    fail(f"Helm chart {expected_name} has unsafe entries")
                if member.size > 64 * 1024 * 1024:
                    fail(f"Helm chart {expected_name} has oversized members")
                total += member.size
                if total > 256 * 1024 * 1024:
                    fail(f"Helm chart {expected_name} expands beyond 256 MiB")
                if (
                    member.isfile()
                    and len(pure.parts) == 2
                    and pure.name == "Chart.yaml"
                ):
                    handle = archive.extractfile(member)
                    data = handle.read(1024 * 1024 + 1) if handle else b""
                    if len(data) > 1024 * 1024:
                        fail("Chart.yaml is oversized")
                    chart_docs.append(data)
                elif member.isfile() and pure.suffix in {".yaml", ".yml", ".tpl"}:
                    if member.size > 4 * 1024 * 1024:
                        fail(f"Helm chart {expected_name} text member is oversized")
                    handle = archive.extractfile(member)
                    data = handle.read(4 * 1024 * 1024 + 1) if handle else b""
                    try:
                        source = data.decode("utf-8")
                    except UnicodeDecodeError:
                        source = ""
                    reject_dynamic_helm(
                        data, f"Helm chart {expected_name} member {member.name}"
                    )
                    for match in IMAGE_LITERAL.finditer(source):
                        declared_images.add(
                            image_reference(match.group(1), "chart image literal")
                        )
                elif member.isfile() and pure.suffix.lower() in HELM_TEXT_SUFFIXES:
                    if member.size > 4 * 1024 * 1024:
                        fail(f"Helm chart {expected_name} text member is oversized")
                    handle = archive.extractfile(member)
                    data = handle.read(4 * 1024 * 1024 + 1) if handle else b""
                    reject_dynamic_helm(
                        data, f"Helm chart {expected_name} member {member.name}"
                    )
                elif member.isfile() and "templates" in pure.parts:
                    if member.size > 4 * 1024 * 1024:
                        fail(f"Helm chart {expected_name} template is oversized")
                    handle = archive.extractfile(member)
                    data = handle.read(4 * 1024 * 1024 + 1) if handle else b""
                    reject_dynamic_helm(
                        data, f"Helm chart {expected_name} member {member.name}"
                    )
                    try:
                        source = data.decode("utf-8")
                    except UnicodeDecodeError:
                        source = ""
                    for match in IMAGE_LITERAL.finditer(source):
                        declared_images.add(
                            image_reference(match.group(1), "chart image literal")
                        )
                if member.isfile() and pure.suffix == ".tgz" and "charts" in pure.parts:
                    handle = archive.extractfile(member)
                    dependency_data = (
                        handle.read(64 * 1024 * 1024 + 1) if handle else b""
                    )
                    if len(dependency_data) > 64 * 1024 * 1024:
                        fail(f"Helm chart {expected_name} dependency is oversized")
                    scan_dependency(dependency_data, member.name, 1)
    finally:
        try:
            fileobj.close()
        finally:
            finish_bound(descriptor, artifact, f"Helm chart {expected_name}")
    if roots != {expected_name} or len(chart_docs) != 1:
        fail(f"Helm chart {expected_name} must contain one exact-name root Chart.yaml")
    try:
        document = load_yaml_or_json(
            chart_docs[0].decode(), source=f"{expected_name}!Chart.yaml"
        )
    except UnicodeDecodeError:
        fail("Chart.yaml is not UTF-8")
    if (
        not isinstance(document, dict)
        or document.get("apiVersion") != "v2"
        or document.get("name") != expected_name
        or str(document.get("version", "")) != expected_version
    ):
        fail(f"Helm chart {expected_name} identity mismatch")
    return {
        "type": "helm-chart",
        "members": len(seen),
        "expanded_bytes": total,
        "root": next(iter(roots)),
        "name": expected_name,
        "version": expected_version,
        "app_version": str(document.get("appVersion", "")),
        "declared_image_references": sorted(declared_images),
    }


def linux_elf_arch(artifact: Artifact) -> str:
    descriptor = open_bound(artifact, "galileoctl")
    try:
        data = os.read(descriptor, 64)
        final = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (final.st_mtime_ns, final.st_ctime_ns, final.st_size) != (
        artifact.mtime_ns,
        artifact.ctime_ns,
        artifact.size,
    ):
        fail("galileoctl changed during inspection")
    if len(data) < 20 or data[:4] != b"\x7fELF" or data[5] not in {1, 2}:
        fail("galileoctl must be a Linux ELF executable")
    machine = int.from_bytes(data[18:20], "little" if data[5] == 1 else "big")
    architecture = {62: "amd64", 183: "arm64", 21: "ppc64le", 22: "s390x"}.get(machine)
    if architecture is None:
        fail("galileoctl ELF architecture is unsupported")
    return architecture


def copy_artifact(artifact: Artifact, destination: Path, mode: int = 0o600) -> None:
    if os.path.lexists(destination):
        fail("bundle destination already exists")
    source = open_bound(artifact, str(artifact.path))
    target = os.open(
        destination,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        mode,
    )
    digest = hashlib.sha256()
    total = 0
    try:
        while True:
            chunk = os.read(source, 4 * 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(target, view)
                view = view[written:]
        os.fsync(target)
        source_final = os.fstat(source)
        target_final = os.fstat(target)
    finally:
        os.close(source)
        os.close(target)
    if (
        total != artifact.size
        or target_final.st_size != artifact.size
        or digest.hexdigest() != artifact.sha256
        or (
            source_final.st_dev,
            source_final.st_ino,
            source_final.st_size,
            source_final.st_mtime_ns,
            source_final.st_ctime_ns,
        )
        != (
            artifact.device,
            artifact.inode,
            artifact.size,
            artifact.mtime_ns,
            artifact.ctime_ns,
        )
    ):
        try:
            destination.unlink()
        except OSError:
            pass
        fail("artifact changed or copy verification failed")


def copy_verified_bundle(source: Path, destination: Path) -> None:
    """Descriptor-copy a previously canonical-verified child bundle."""
    if os.path.lexists(destination):
        fail("child bundle destination already exists")
    destination.mkdir(mode=0o700)
    for current, dirs, files in os.walk(source, topdown=True, followlinks=False):
        dirs.sort()
        files.sort()
        relative_root = Path(current).relative_to(source)
        target_root = destination / relative_root
        for dirname in dirs:
            (target_root / dirname).mkdir(mode=0o700)
        for filename in files:
            source_path = Path(current) / filename
            artifact = secure_file(source_path, "verified child bundle artifact")
            copy_artifact(
                artifact,
                target_root / filename,
                stat.S_IMODE(os.lstat(source_path).st_mode),
            )


def write(path: Path, value: bytes | str, mode: int = 0o600) -> None:
    payload = value if isinstance(value, bytes) else value.encode()
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0), mode
    )
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_json(path: Path, value: object) -> None:
    write(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def canonical_air_gap_contract(
    *,
    console: str,
    release_id: str,
    environment: str,
    optional_components: dict[str, str],
    target_arches: set[str],
    destination: str,
    registry_suffixes: set[str],
    registry_hosts: set[str],
    allowed_endpoints: set[str],
    endpoint_suffixes: set[str],
    endpoint_hosts: set[str],
    cse_reference: str,
    source_hashes: dict[str, str],
) -> dict:
    return {
        "schema": "galileo-on-prem-air-gap-normalized-spec/v1",
        "galileo_console_url": console,
        "release": {
            "id": release_id,
            "environment": environment,
            "target_architectures": sorted(target_arches),
            "optional_components": {
                key: optional_components[key] for key in sorted(optional_components)
            },
        },
        "registry": {
            "destination": destination,
            "internal_dns_suffixes": sorted(registry_suffixes),
            "exact_internal_hosts": sorted(registry_hosts),
        },
        "no_egress": {
            "strict": True,
            "allowed_endpoints": sorted(allowed_endpoints),
            "internal_dns_suffixes": sorted(endpoint_suffixes),
            "exact_internal_hosts": sorted(endpoint_hosts),
        },
        "approval": {
            "cse_reference": cse_reference,
            "release_manifest_approved": True,
        },
        "source_hashes": dict(sorted(source_hashes.items())),
    }


def completion_gates(models: list[dict]) -> list[str]:
    """Expose evidence contracts the current Stack producer cannot yet emit."""
    gates = ["endpoint_rewrite_evidence_missing"]
    if models:
        gates.append("stack_model_evidence_missing")
    return sorted(gates)


def canonical_air_gap_coverage(
    use_counts: dict[str, int], open_gates: list[str] | None = None
) -> dict:
    category_features = [
        f"{use}-images" if use_counts[use] else f"{use}-images-explicitly-empty"
        for use in sorted(USES)
    ]
    return {
        "schema": "galileo-on-prem-air-gap-coverage/v1",
        "features": [
            "charts",
            "galileoctl",
            "model-transfer-artifacts",
            "digests",
            "architectures",
            "scan-attestations",
            "safe-archives",
            "private-registry-mapping",
            "endpoint-host-inventory",
            *category_features,
        ],
        "image_use_evidence": use_counts,
        "uncovered": sorted(open_gates or []),
        "unowned": [],
        "unclassified_runtime_inventory": [],
    }


def replace_json(path: Path, value: object) -> None:
    temporary = path.with_name(path.name + ".new")
    write_json(temporary, value)
    os.replace(temporary, path)
    fsync_directory(path.parent)


def fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def bundle_files(root: Path) -> list[Path]:
    paths: list[Path] = []
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        dirs.sort()
        files.sort()
        for name in files:
            if name not in {"MANIFEST.sha256", "BUNDLE.sha256"}:
                paths.append(Path(current) / name)
    return sorted(paths, key=lambda item: item.relative_to(root).as_posix())


def manifest_details(root: Path) -> tuple[bytes, dict[str, Artifact]]:
    lines = []
    artifacts: dict[str, Artifact] = {}
    for path in bundle_files(root):
        artifact = secure_file(path, "bundle payload")
        relative = path.relative_to(root).as_posix()
        artifacts[relative] = artifact
        lines.append(
            f"{artifact.sha256}  {stat.S_IMODE(os.lstat(path).st_mode):04o}  {relative}"
        )
    return ("\n".join(lines) + "\n").encode(), artifacts


def manifest_payload(root: Path) -> bytes:
    return manifest_details(root)[0]


def identity_manifest(manifest: bytes, metadata: dict) -> bytes:
    pending = dict(metadata)
    pending["bundle_sha256"] = "PENDING"
    digest = hashlib.sha256(
        (json.dumps(pending, indent=2, sort_keys=True) + "\n").encode()
    ).hexdigest()
    lines: list[str] = []
    found = False
    try:
        source_lines = manifest.decode("ascii").splitlines()
    except UnicodeDecodeError:
        fail("bundle manifest is not ASCII")
    for line in source_lines:
        parts = line.split("  ", 2)
        if (
            len(parts) != 3
            or not HEX64.fullmatch(parts[0])
            or not re.fullmatch(r"0[0-7]{3}", parts[1])
        ):
            fail("bundle manifest line is malformed")
        if parts[2] == "metadata.json":
            if found:
                fail("bundle manifest contains duplicate metadata")
            parts[0] = digest
            found = True
        lines.append("  ".join(parts))
    if not found:
        fail("bundle manifest lacks metadata")
    return ("\n".join(lines) + "\n").encode()


def verify_bundle(root: Path) -> dict:
    try:
        info = os.lstat(root)
    except OSError:
        fail("bundle is unavailable")
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        fail("bundle root must be current-user-owned mode 0700")
    for current, dirs, files in os.walk(root, followlinks=False):
        for name in dirs:
            item = os.lstat(Path(current) / name)
            if (
                not stat.S_ISDIR(item.st_mode)
                or stat.S_ISLNK(item.st_mode)
                or item.st_uid != os.getuid()
                or stat.S_IMODE(item.st_mode) != 0o700
            ):
                fail("bundle directory contract failed")
        for name in files:
            item = os.lstat(Path(current) / name)
            if (
                not stat.S_ISREG(item.st_mode)
                or stat.S_ISLNK(item.st_mode)
                or item.st_uid != os.getuid()
                or item.st_nlink != 1
                or stat.S_IMODE(item.st_mode) not in {0o600, 0o700}
            ):
                fail("bundle file contract failed")
    manifest = root / "MANIFEST.sha256"
    digest_file = root / "BUNDLE.sha256"
    manifest_artifact = secure_read(manifest, "bundle manifest")
    digest_artifact = secure_read(digest_file, "bundle digest")
    payload, artifacts = manifest_details(root)
    if manifest_artifact.data != payload:
        fail("bundle payload or manifest drifted")
    metadata_artifact = artifacts.get("metadata.json")
    if metadata_artifact is None:
        fail("bundle lacks metadata")
    metadata = strict_json_mapping(metadata_artifact, "bundle metadata", canonical=True)
    only(
        metadata,
        {
            "schema",
            "bundle_sha256",
            "release_id",
            "environment",
            "galileo_console_url",
            "target_architectures",
            "registry_destination",
            "registry_internal_dns_suffixes",
            "registry_exact_internal_hosts",
            "internal_dns_suffixes",
            "exact_internal_hosts",
            "cse_reference",
            "source_spec_sha256",
            "source_image_manifest_sha256",
            "source_chart_inventory_sha256",
            "chart_inventory_sha256",
            "stack_bundle_sha256",
            "stack_seed_bundle_path",
            "source_stack_image_evidence_sha256",
            "stack_image_evidence_sha256",
            "source_stack_endpoint_evidence_sha256",
            "stack_endpoint_evidence_sha256",
            "stack_seed",
            "stack_endpoint_seed",
            "endpoint_inventory_sha256",
            "source_hashes",
            "optional_components",
            "child_image_evidence",
            "charts",
            "galileoctl",
            "models",
            "images",
            "stack_images",
            "child_images",
            "open_gates",
            "registry_push_execution",
        },
        "bundle metadata",
    )
    digest = hashlib.sha256(identity_manifest(payload, metadata)).hexdigest()
    try:
        recorded = digest_artifact.data.decode("ascii").strip()
    except UnicodeDecodeError:
        fail("bundle digest is not ASCII")
    if recorded != digest:
        fail("bundle identity drifted")
    if metadata.get("schema") != SCHEMA or metadata.get("bundle_sha256") != digest:
        fail("bundle metadata is invalid")
    contract_artifact = artifacts.get("normalized-spec.json")
    if contract_artifact is None:
        fail("bundle lacks normalized deployment spec")
    contract = strict_json_mapping(
        contract_artifact, "normalized deployment spec", canonical=True
    )
    contract_bytes = artifact_bytes(contract_artifact, "normalized deployment spec")
    only(
        contract,
        {
            "schema",
            "galileo_console_url",
            "release",
            "registry",
            "no_egress",
            "approval",
            "source_hashes",
        },
        "normalized deployment spec",
    )
    if (
        contract.get("schema") != "galileo-on-prem-air-gap-normalized-spec/v1"
        or contract_bytes != canonical_json(contract)
    ):
        fail("normalized deployment spec is not canonical")
    for name, fields in (
        (
            "release",
            {"id", "environment", "target_architectures", "optional_components"},
        ),
        (
            "registry",
            {"destination", "internal_dns_suffixes", "exact_internal_hosts"},
        ),
        (
            "no_egress",
            {
                "strict",
                "allowed_endpoints",
                "internal_dns_suffixes",
                "exact_internal_hosts",
            },
        ),
        ("approval", {"cse_reference", "release_manifest_approved"}),
    ):
        value = contract.get(name)
        if not isinstance(value, dict):
            fail(f"normalized deployment spec {name} is not a mapping")
        only(value, fields, f"normalized deployment spec {name}")
    source_hashes = contract.get("source_hashes")
    if (
        not isinstance(source_hashes, dict)
        or any(
            not isinstance(key, str)
            or not isinstance(value, str)
            or not HEX64.fullmatch(value)
            for key, value in source_hashes.items()
        )
        or metadata.get("source_hashes") != source_hashes
    ):
        fail("normalized source artifact hash contract is invalid")
    release_id = text(metadata, "release_id", "metadata")
    if not RELEASE_ID.fullmatch(release_id) or metadata.get("environment") not in {
        "development",
        "staging",
        "production",
    }:
        fail("bundle release identity is invalid")
    origin(text(metadata, "galileo_console_url", "metadata"))
    destination = text(metadata, "registry_destination", "metadata")
    if "://" in destination or "/" not in destination:
        fail("bundle registry destination is invalid")
    text(metadata, "cse_reference", "metadata")
    suffixes = metadata.get("internal_dns_suffixes")
    exact_hosts = metadata.get("exact_internal_hosts")
    registry_suffixes = metadata.get("registry_internal_dns_suffixes")
    registry_hosts = metadata.get("registry_exact_internal_hosts")
    if (
        not isinstance(suffixes, list)
        or any(not isinstance(item, str) for item in suffixes)
        or suffixes != sorted(set(suffixes))
        or not isinstance(exact_hosts, list)
        or any(not isinstance(item, str) for item in exact_hosts)
        or exact_hosts != sorted(set(exact_hosts))
        or not isinstance(registry_suffixes, list)
        or any(not isinstance(item, str) for item in registry_suffixes)
        or registry_suffixes != sorted(set(registry_suffixes))
        or not isinstance(registry_hosts, list)
        or any(not isinstance(item, str) for item in registry_hosts)
        or registry_hosts != sorted(set(registry_hosts))
    ):
        fail("bundle internal DNS policy is invalid")
    suffix_set = {
        validate_dns_suffix(item, "bundle no-egress internal DNS suffix")
        for item in suffixes
    }
    host_set = {
        endpoint_hostname(validate_hostport(item, "bundle no-egress exact host"))
        for item in exact_hosts
    }
    registry_suffix_set = {
        validate_dns_suffix(item, "bundle registry internal DNS suffix")
        for item in registry_suffixes
    }
    registry_host_set = {
        endpoint_hostname(validate_hostport(item, "bundle registry exact host"))
        for item in registry_hosts
    }
    destination = registry(destination, registry_host_set, registry_suffix_set)
    target_arches_raw = metadata.get("target_architectures")
    if (
        not isinstance(target_arches_raw, list)
        or not target_arches_raw
        or any(not isinstance(value, str) for value in target_arches_raw)
        or target_arches_raw != sorted(set(target_arches_raw))
        or not set(target_arches_raw) <= ARCHES
    ):
        fail("bundle target architectures are invalid")
    target_arches = set(target_arches_raw)
    optional_components = metadata.get("optional_components")
    if (
        not isinstance(optional_components, dict)
        or set(optional_components) != {"agent-control", "luna-studio"}
        or any(
            value not in {"disabled", "umbrella", "standalone"}
            for value in optional_components.values()
        )
    ):
        fail("bundle optional-component ownership classification is invalid")
    contract_release = contract["release"]
    contract_registry = contract["registry"]
    contract_no_egress = contract["no_egress"]
    contract_approval = contract["approval"]
    if (
        contract.get("galileo_console_url") != metadata["galileo_console_url"]
        or contract_release
        != {
            "id": release_id,
            "environment": metadata["environment"],
            "target_architectures": target_arches_raw,
            "optional_components": optional_components,
        }
        or contract_registry
        != {
            "destination": destination,
            "internal_dns_suffixes": registry_suffixes,
            "exact_internal_hosts": registry_hosts,
        }
        or contract_no_egress.get("strict") is not True
        or contract_approval
        != {
            "cse_reference": metadata["cse_reference"],
            "release_manifest_approved": True,
        }
    ):
        fail("bundle metadata differs from normalized deployment semantics")
    for key in (
        "source_spec_sha256",
        "source_image_manifest_sha256",
        "source_chart_inventory_sha256",
        "chart_inventory_sha256",
        "stack_bundle_sha256",
        "source_stack_image_evidence_sha256",
        "stack_image_evidence_sha256",
        "source_stack_endpoint_evidence_sha256",
        "stack_endpoint_evidence_sha256",
        "endpoint_inventory_sha256",
    ):
        if not isinstance(metadata.get(key), str) or not HEX64.fullmatch(metadata[key]):
            fail(f"metadata.{key} is invalid")

    def bundle_artifact(relative: object, label: str) -> Artifact:
        if not isinstance(relative, str):
            fail(f"{label} bundle path is invalid")
        pure = normalized_member(relative, label)
        if pure.as_posix() != relative or relative not in artifacts:
            fail(f"{label} bundle path is missing or non-canonical")
        return artifacts[relative]

    expected_files = {
        "metadata.json",
        "normalized-spec.json",
        "image-manifest.json",
        "no-egress-report.json",
        "coverage-report.json",
        "evidence/chart-image-inventory.json",
        "evidence/runtime-endpoints.json",
        "evidence/stack-rendered-image-inventory.json",
        "evidence/stack-rendered-endpoint-inventory.json",
        "tools/galileoctl",
        "MANIFEST.sha256",
        "BUNDLE.sha256",
    }
    expected_dirs = {
        "charts",
        "images",
        "scans",
        "models",
        "tools",
        "evidence",
        "evidence/stack-seed-bundle",
    }
    child_records = metadata.get("child_image_evidence")
    if not isinstance(child_records, list):
        fail("bundle child image evidence inventory is invalid")
    observed_child_components: set[str] = set()
    for index, record in enumerate(child_records):
        if not isinstance(record, dict):
            fail(f"bundle child image evidence row {index} is invalid")
        only(
            record,
            {
                "component",
                "bundle_path",
                "bundle_sha256",
                "evidence_path",
                "evidence_sha256",
                "endpoint_evidence_path",
                "endpoint_evidence_sha256",
                "chart",
            },
            f"metadata.child_image_evidence[{index}]",
        )
        component = text(record, "component", f"metadata.child_image_evidence[{index}]")
        if component in observed_child_components:
            fail("bundle child image evidence components are duplicated")
        observed_child_components.add(component)
        if (
            record.get("bundle_path") != f"evidence/child-bundles/{component}"
            or record.get("evidence_path") != f"evidence/child-images/{component}.json"
            or record.get("endpoint_evidence_path")
            != f"evidence/child-endpoints/{component}.json"
            or not HEX64.fullmatch(str(record.get("bundle_sha256", "")))
            or not HEX64.fullmatch(str(record.get("evidence_sha256", "")))
            or not HEX64.fullmatch(str(record.get("endpoint_evidence_sha256", "")))
        ):
            fail("bundle child image evidence paths/hashes are invalid")
        expected_files.add(record["evidence_path"])
        expected_files.add(record["endpoint_evidence_path"])
    require_child_evidence_coverage(optional_components, observed_child_components)
    if child_records:
        expected_dirs.update(
            {
                "evidence/child-bundles",
                "evidence/child-images",
                "evidence/child-endpoints",
            }
        )
    stack_seed_bundle_path = metadata.get("stack_seed_bundle_path")
    expected_stack_seed_path = (
        f"evidence/stack-seed-bundle/{metadata['stack_bundle_sha256']}"
    )
    if stack_seed_bundle_path != expected_stack_seed_path:
        fail("bundle Stack seed path is not deterministic")
    (
        verified_stack_digest,
        verified_stack_charts,
        verified_stack_sources,
        verified_stack_document,
        verified_stack_source_owners,
    ) = verified_stack_evidence(
        str(root / stack_seed_bundle_path),
        metadata["stack_bundle_sha256"],
        str(root / "evidence" / "stack-rendered-image-inventory.json"),
        metadata["stack_image_evidence_sha256"],
    )
    if verified_stack_digest != metadata["stack_bundle_sha256"]:
        fail("bundled Stack seed verification returned another digest")
    verified_stack_endpoint_document, verified_stack_endpoint_rows = (
        verified_stack_endpoint_evidence(
            str(root / "evidence" / "stack-rendered-endpoint-inventory.json"),
            metadata["stack_endpoint_evidence_sha256"],
            str(root / stack_seed_bundle_path),
            verified_stack_document,
        )
    )
    for current, dirs, files in os.walk(
        root / stack_seed_bundle_path, topdown=True, followlinks=False
    ):
        relative_root = Path(current).relative_to(root).as_posix()
        expected_dirs.add(relative_root)
        for dirname in dirs:
            expected_dirs.add(f"{relative_root}/{dirname}")
        for filename in files:
            expected_files.add(f"{relative_root}/{filename}")
    verified_child_sources: set[str] = set()
    verified_child_charts: list[dict] = []
    verified_child_source_owners: dict[str, set[str]] = {}
    verified_child_documents: dict[str, dict] = {}
    verified_child_endpoint_documents: dict[str, dict] = {}
    verified_child_endpoint_rows: dict[str, list[dict]] = {}
    for record in child_records:
        component = record["component"]
        (
            chart,
            sources_for_child,
            document,
            owners,
            endpoint_document,
            endpoint_rows,
        ) = verified_child_evidence(
            {
                "component": component,
                "bundle": str(root / record["bundle_path"]),
                "bundle_sha256": record["bundle_sha256"],
                "evidence_file": str(root / record["evidence_path"]),
                "evidence_sha256": record["evidence_sha256"],
                "endpoint_evidence_file": str(root / record["endpoint_evidence_path"]),
                "endpoint_evidence_sha256": record["endpoint_evidence_sha256"],
            },
            metadata["stack_bundle_sha256"],
            verified_stack_document["target"],
        )
        if chart != record.get("chart"):
            fail(f"{component} bundled chart evidence differs from metadata")
        verified_child_charts.append(chart)
        verified_child_sources.update(sources_for_child)
        verified_child_documents[component] = document
        verified_child_endpoint_documents[component] = endpoint_document
        verified_child_endpoint_rows[component] = endpoint_rows
        for source, source_components in owners.items():
            verified_child_source_owners.setdefault(source, set()).update(
                source_components
            )
        for current, dirs, files in os.walk(
            root / record["bundle_path"], topdown=True, followlinks=False
        ):
            relative_root = Path(current).relative_to(root).as_posix()
            expected_dirs.add(relative_root)
            for dirname in dirs:
                expected_dirs.add(f"{relative_root}/{dirname}")
            for filename in files:
                expected_files.add(f"{relative_root}/{filename}")
    images = metadata.get("images")
    if not isinstance(images, list) or not images:
        fail("bundle image inventory is empty")
    sources: set[str] = set()
    mirrors: set[str] = set()
    for index, item in enumerate(images):
        if not isinstance(item, dict):
            fail("bundle image entry is invalid")
        only(
            item,
            {
                "source",
                "source_digest",
                "mirror",
                "mirror_digest",
                "archive_file",
                "archive_sha256",
                "architectures",
                "uses",
                "scan_attestation_file",
                "source_scan_attestation_sha256",
                "scan_attestation_sha256",
            },
            f"metadata.images[{index}]",
        )
        source = image_reference(
            text(item, "source", f"metadata.images[{index}]"), "bundle image source"
        )
        mirror = image_reference(
            text(item, "mirror", f"metadata.images[{index}]"), "bundle image mirror"
        )
        validate_source_mirror_roles(
            source, mirror, destination, f"metadata.images[{index}]"
        )
        if source in sources or mirror in mirrors:
            fail("bundle image references are duplicated or outside the destination")
        sources.add(source)
        mirrors.add(mirror)
        source_digest = text(item, "source_digest", f"metadata.images[{index}]")
        if (
            not OCI_DIGEST.fullmatch(source_digest)
            or item.get("mirror_digest") != source_digest
        ):
            fail("bundle image digest identity is invalid")
        arches = item.get("architectures")
        uses = item.get("uses")
        if (
            not isinstance(arches, list)
            or not arches
            or any(not isinstance(value, str) for value in arches)
            or arches != sorted(set(arches))
            or not set(arches) <= ARCHES
            or not isinstance(uses, list)
            or any(not isinstance(value, str) for value in uses)
            or uses != sorted(set(uses))
            or not set(uses) <= USES
            or not uses
        ):
            fail("bundle image architecture/use evidence is invalid")
        archive_file = item.get("archive_file")
        scan_file = item.get("scan_attestation_file")
        if (
            archive_file != f"images/{index:04d}.oci.tar"
            or scan_file != f"scans/{index:04d}.json"
        ):
            fail("bundle image paths are non-deterministic")
        archive = bundle_artifact(archive_file, "OCI archive")
        scan = bundle_artifact(scan_file, "scan attestation")
        if (
            item.get("archive_sha256") != archive.sha256
            or item.get("scan_attestation_sha256") != scan.sha256
            or item.get("source_scan_attestation_sha256") != scan.sha256
        ):
            fail("bundle image artifact hashes are invalid")
        identity = oci_identity(archive)
        if identity["root_digest"] != source_digest or set(
            identity["architectures"]
        ) != set(arches):
            fail("bundle OCI identity/architecture evidence is invalid")
        scan_doc = strict_json_mapping(scan, "bundle scan attestation", canonical=True)
        only(
            scan_doc,
            {
                "schema",
                "subject",
                "image_digest",
                "passed",
                "scanner",
                "scanner_version",
                "scanned_at",
                "policy",
            },
            "bundle scan attestation",
        )
        if (
            scan_doc.get("schema") != "galileo-image-scan-attestation/v1"
            or scan_doc.get("subject") != source
            or scan_doc.get("image_digest") != source_digest
            or scan_doc.get("passed") is not True
        ):
            fail("bundle scan attestation is invalid")
        text(scan_doc, "scanner", "scan")
        text(scan_doc, "scanner_version", "scan")
        text(scan_doc, "policy", "scan")
        timestamp(scan_doc.get("scanned_at"), "scan.scanned_at")
        expected_scan_doc = {
            "schema": "galileo-image-scan-attestation/v1",
            "subject": source,
            "image_digest": source_digest,
            "passed": True,
            "scanner": text(scan_doc, "scanner", "scan"),
            "scanner_version": text(scan_doc, "scanner_version", "scan"),
            "scanned_at": timestamp(scan_doc.get("scanned_at"), "scan.scanned_at"),
            "policy": text(scan_doc, "policy", "scan"),
        }
        if scan_doc != expected_scan_doc:
            fail("bundle scan attestation differs from its canonical semantics")
        expected_files.update({archive_file, scan_file})

    verified_stack_mirrors = set(verified_stack_sources)
    verified_child_mirrors = set(verified_child_sources)
    verified_mirror_owners = {
        mirror: set(owners) for mirror, owners in verified_stack_source_owners.items()
    }
    for mirror, owners in verified_child_source_owners.items():
        verified_mirror_owners.setdefault(mirror, set()).update(owners)
    bind_rendered_mirrors(
        images, verified_mirror_owners, "bundled Stack/child rendered images"
    )
    require_image_architecture_coverage(
        [verified_stack_document, *verified_child_documents.values()],
        images,
        target_arches,
    )
    verified_stack_sources = {
        item["source"] for item in images if item["mirror"] in verified_stack_mirrors
    }
    verified_child_sources = {
        item["source"] for item in images if item["mirror"] in verified_child_mirrors
    }
    expected_stack_images = [
        item for item in images if item["source"] in verified_stack_sources
    ]
    expected_child_images = [
        item for item in images if item["source"] in verified_child_sources
    ]
    if metadata.get("stack_images") != expected_stack_images:
        fail("Stack-scoped image contract differs from exact Stack seed evidence")
    if metadata.get("child_images") != expected_child_images:
        fail("child-scoped image contract differs from exact child evidence")
    if not expected_stack_images:
        fail("Stack-scoped image contract is empty")

    image_manifest_doc = strict_json_mapping(
        bundle_artifact("image-manifest.json", "image manifest"),
        "image manifest",
        canonical=True,
    )
    if image_manifest_doc != {
        "schema": "galileo-air-gap-image-manifest/v1",
        "release": release_id,
        "images": images,
    }:
        fail("normalized bundle image manifest disagrees with metadata")

    charts = metadata.get("charts")
    if not isinstance(charts, list) or not charts:
        fail("bundle chart inventory is empty")
    chart_names: set[str] = set()
    for index, item in enumerate(charts):
        if not isinstance(item, dict):
            fail("bundle chart entry is invalid")
        only(
            item,
            {"name", "version", "file", "sha256", "inspection"},
            f"metadata.charts[{index}]",
        )
        name = text(item, "name", f"metadata.charts[{index}]")
        version = text(item, "version", f"metadata.charts[{index}]")
        if (
            not SAFE_NAME.fullmatch(name)
            or not SAFE_VERSION.fullmatch(version)
            or name in chart_names
            or item.get("file") != f"charts/{index:04d}-{name}.tgz"
        ):
            fail("bundle chart identity/path is invalid")
        chart_names.add(name)
        artifact = bundle_artifact(item["file"], "Helm chart")
        if item.get("sha256") != artifact.sha256 or item.get(
            "inspection"
        ) != inspect_helm_chart(artifact, name, version):
            fail("bundle Helm chart digest/inspection is invalid")
        expected_files.add(item["file"])

    cli = metadata.get("galileoctl")
    if not isinstance(cli, dict):
        fail("bundle galileoctl metadata is invalid")
    only(
        cli, {"version", "file", "sha256", "os", "architecture"}, "metadata.galileoctl"
    )
    cli_artifact = bundle_artifact(cli.get("file"), "galileoctl")
    if (
        cli.get("file") != "tools/galileoctl"
        or cli.get("os") != "linux"
        or cli.get("architecture") not in target_arches
        or not SAFE_VERSION.fullmatch(text(cli, "version", "galileoctl"))
        or cli.get("sha256") != cli_artifact.sha256
        or linux_elf_arch(cli_artifact) != cli.get("architecture")
    ):
        fail("bundle galileoctl identity is invalid")

    models = metadata.get("models")
    if not isinstance(models, list):
        fail("bundle model inventory is invalid")
    model_names: set[str] = set()
    for index, item in enumerate(models):
        if not isinstance(item, dict):
            fail("bundle model entry is invalid")
        only(
            item,
            {"name", "version", "file", "sha256", "architectures", "inspection"},
            f"metadata.models[{index}]",
        )
        name = text(item, "name", f"metadata.models[{index}]")
        version = text(item, "version", f"metadata.models[{index}]")
        arches = item.get("architectures")
        if (
            not SAFE_NAME.fullmatch(name)
            or not SAFE_VERSION.fullmatch(version)
            or name in model_names
            or item.get("file") != f"models/{index:04d}.bundle"
            or not isinstance(arches, list)
            or any(not isinstance(value, str) for value in arches)
            or arches != sorted(set(arches))
            or not target_arches <= set(arches) <= ARCHES
        ):
            fail("bundle model identity/path/architectures are invalid")
        model_names.add(name)
        artifact = bundle_artifact(item["file"], "model archive")
        inspection = safe_archive(artifact, "model archive")
        if (
            item.get("sha256") != artifact.sha256
            or inspection.get("type") != "archive"
            or item.get("inspection") != inspection
        ):
            fail("bundle model archive evidence is invalid")
        expected_files.add(item["file"])
    if (
        metadata.get("open_gates") != completion_gates(models)
        or metadata.get("registry_push_execution")
        != "galileo-cse-operator-handoff-only"
    ):
        fail("bundle completion/mutation boundary is invalid")

    expected_source_hashes = {
        "deployment_spec": metadata["source_spec_sha256"],
        "image_manifest": metadata["source_image_manifest_sha256"],
        "chart_inventory": metadata["source_chart_inventory_sha256"],
        "stack_bundle": metadata["stack_bundle_sha256"],
        "stack_image_evidence": metadata["source_stack_image_evidence_sha256"],
        "stack_endpoint_evidence": metadata["source_stack_endpoint_evidence_sha256"],
        "galileoctl": cli["sha256"],
        **{f"chart:{item['name']}": item["sha256"] for item in charts},
        **{f"model:{item['name']}": item["sha256"] for item in models},
        **{f"oci:{item['source']}": item["archive_sha256"] for item in images},
        **{
            f"scan:{item['source']}": item["source_scan_attestation_sha256"]
            for item in images
        },
        **{
            f"child-bundle:{item['component']}": item["bundle_sha256"]
            for item in child_records
        },
        **{
            f"child-image-evidence:{item['component']}": item["evidence_sha256"]
            for item in child_records
        },
        **{
            f"child-endpoint-evidence:{item['component']}": item[
                "endpoint_evidence_sha256"
            ]
            for item in child_records
        },
    }
    if source_hashes != expected_source_hashes:
        fail("normalized source artifact hashes differ from exact bundled metadata")

    chart_artifact = bundle_artifact(
        "evidence/chart-image-inventory.json", "chart inventory"
    )
    endpoint_artifact = bundle_artifact(
        "evidence/runtime-endpoints.json", "endpoint inventory"
    )
    stack_image_artifact = bundle_artifact(
        "evidence/stack-rendered-image-inventory.json",
        "Stack rendered image inventory",
    )
    stack_endpoint_artifact = bundle_artifact(
        "evidence/stack-rendered-endpoint-inventory.json",
        "Stack rendered endpoint inventory",
    )
    if (
        metadata["chart_inventory_sha256"] != chart_artifact.sha256
        or metadata["source_chart_inventory_sha256"] != chart_artifact.sha256
        or metadata["endpoint_inventory_sha256"] != endpoint_artifact.sha256
        or metadata["stack_image_evidence_sha256"] != stack_image_artifact.sha256
        or metadata["source_stack_image_evidence_sha256"] != stack_image_artifact.sha256
        or metadata["stack_endpoint_evidence_sha256"] != stack_endpoint_artifact.sha256
        or metadata["source_stack_endpoint_evidence_sha256"]
        != stack_endpoint_artifact.sha256
    ):
        fail("normalized evidence hashes disagree with metadata")
    stack_image_doc = strict_json_mapping(
        stack_image_artifact, "Stack rendered image inventory", canonical=True
    )
    only(
        stack_image_doc,
        {
            "schema",
            "generated_by",
            "source_bundle_sha256",
            "charts",
            "inputs",
            "redacted_render_sha256",
            "target",
            "created_at",
            "items",
        },
        "Stack rendered image inventory",
    )
    stack_rows = stack_image_doc.get("items")
    if (
        stack_image_doc.get("schema")
        != "galileo-on-prem-stack-rendered-image-inventory/v1"
        or stack_image_doc.get("generated_by") != "galileo-on-prem-stack-setup"
        or stack_image_doc.get("source_bundle_sha256")
        != metadata["stack_bundle_sha256"]
        or not isinstance(stack_rows, list)
        or not stack_rows
        or canonical_json(stack_image_doc)
        != artifact_bytes(stack_image_artifact, "Stack rendered image inventory")
    ):
        fail("Stack rendered image inventory is not canonical/bundle-bound")
    expected_stack_seed = {
        "evidence_sha256": stack_image_artifact.sha256,
        "source_bundle_sha256": stack_image_doc["source_bundle_sha256"],
        "charts": stack_image_doc["charts"],
        "inputs": stack_image_doc["inputs"],
        "redacted_render_sha256": stack_image_doc["redacted_render_sha256"],
        "target": stack_image_doc["target"],
        "items": stack_image_doc["items"],
    }
    if metadata.get("stack_seed") != expected_stack_seed:
        fail("Stack seed contract differs from its canonical embedded evidence")
    stack_endpoint_doc = strict_json_mapping(
        stack_endpoint_artifact, "Stack rendered endpoint inventory", canonical=True
    )
    expected_stack_endpoint_seed = {
        "evidence_sha256": stack_endpoint_artifact.sha256,
        "source_bundle_sha256": stack_endpoint_doc["source_bundle_sha256"],
        "charts": stack_endpoint_doc["charts"],
        "inputs": stack_endpoint_doc["inputs"],
        "redacted_render_sha256": stack_endpoint_doc["redacted_render_sha256"],
        "target": stack_endpoint_doc["target"],
        "items": stack_endpoint_doc["items"],
    }
    if metadata.get("stack_endpoint_seed") != expected_stack_endpoint_seed:
        fail("Stack endpoint seed differs from canonical embedded evidence")
    if stack_image_doc != verified_stack_document:
        fail("embedded Stack image evidence differs after seed bundle verification")
    if stack_endpoint_doc != verified_stack_endpoint_document or canonical_json(
        stack_endpoint_doc
    ) != artifact_bytes(stack_endpoint_artifact, "Stack rendered endpoint inventory"):
        fail("embedded Stack endpoint evidence differs after seed verification")
    exact_stack_sources: set[str] = set()
    for index, row in enumerate(stack_rows):
        if (
            not isinstance(row, dict)
            or set(row)
            != {
                "release",
                "source_object",
                "container_type",
                "container",
                "image",
                "digest",
                "eligible_architectures",
            }
            or not isinstance(row.get("image"), str)
            or not isinstance(row.get("digest"), str)
            or not OCI_DIGEST.fullmatch(row["digest"])
            or not row["image"].endswith("@" + row["digest"])
        ):
            fail(f"Stack rendered image inventory row {index} is invalid")
        exact_stack_sources.add(
            image_reference(
                row["image"].rsplit("@", 1)[0],
                f"Stack rendered image inventory row {index}",
            )
        )
    if exact_stack_sources != verified_stack_mirrors:
        fail("Stack mirror set differs after canonical seed verification")
    chart_doc, chart_sources, use_counts, declared_charts = parse_chart_inventory(
        chart_artifact, release_id
    )
    exact_combined_sources = verified_stack_sources | verified_child_sources
    if exact_combined_sources != chart_sources:
        fail(
            "chart inventory differs from exact Stack plus standalone child evidence union"
        )
    if chart_sources != sources:
        fail("bundle image manifest contains missing or unbound extra image sources")
    evidence_digests: dict[str, str] = {}
    for document in [verified_stack_document, *verified_child_documents.values()]:
        for row in document["items"]:
            source = row["image"].rsplit("@", 1)[0]
            previous = evidence_digests.setdefault(source, row["digest"])
            if previous != row["digest"]:
                fail("rendered evidence disagrees on a shared image digest")
    if any(
        evidence_digests.get(item["mirror"]) != item["mirror_digest"]
        or item["mirror_digest"] != item["source_digest"]
        for item in images
    ):
        fail("bundle image digests differ from exact rendered evidence")
    for row in chart_doc["images"]:
        image = next(value for value in images if value["source"] == row["source"])
        if row["use"] not in image["uses"]:
            fail("bundle chart/image use classification disagrees")
    actual_charts = sorted(
        (
            {"name": item["name"], "version": item["version"], "sha256": item["sha256"]}
            for item in charts
        ),
        key=lambda item: item["name"],
    )
    exact_evidence_charts = sorted(
        [*verified_stack_charts, *verified_child_charts],
        key=lambda item: item["name"],
    )
    if actual_charts != declared_charts or declared_charts != exact_evidence_charts:
        fail("bundle chart inventory is not bound to exact chart artifacts")
    declared_literals = {
        reference
        for item in charts
        for reference in item["inspection"]["declared_image_references"]
    }
    if not declared_literals <= chart_sources:
        fail(
            "bundle chart inventory omits a literal image reference derived from a chart"
        )
    endpoint_doc = parse_endpoints(endpoint_artifact, release_id)
    endpoint_union: list[dict] = [
        *({"owner": "galileo-stack", **row} for row in verified_stack_endpoint_rows),
        *(
            {"owner": component, **row}
            for component, rows in verified_child_endpoint_rows.items()
            for row in rows
        ),
    ]
    endpoint_union.sort(
        key=lambda item: (
            item["owner"],
            item["host"],
            item["purpose"],
            item["source"],
        )
    )
    expected_endpoint_doc = {
        "schema": "galileo-runtime-endpoints/v1",
        "release": release_id,
        "endpoints": [
            {
                "name": f"{item['owner']}-{index:04d}",
                "host": item["host"],
                "purpose": f"{item['owner']}: {item['purpose']}",
                "enabled": True,
            }
            for index, item in enumerate(endpoint_union)
        ],
    }
    if endpoint_doc != expected_endpoint_doc:
        fail("runtime endpoint inventory differs from exact Stack/child evidence union")
    report = strict_json_mapping(
        bundle_artifact("no-egress-report.json", "no-egress report"),
        "no-egress report",
        canonical=True,
    )
    only(
        report,
        {
            "schema",
            "release",
            "strict",
            "allowed_endpoints",
            "internal_dns_suffixes",
            "exact_internal_hosts",
            "unapproved_endpoints",
            "unvalidated_gates",
        },
        "no-egress report",
    )
    allowed = report.get("allowed_endpoints")
    if (
        report.get("schema") != "galileo-no-egress-report/v1"
        or report.get("release") != release_id
        or report.get("strict") is not False
        or report.get("unapproved_endpoints") != []
        or report.get("unvalidated_gates") != metadata["open_gates"]
        or not isinstance(allowed, list)
        or allowed != sorted(set(allowed))
        or report.get("internal_dns_suffixes") != suffixes
        or report.get("exact_internal_hosts") != exact_hosts
    ):
        fail("bundle no-egress report is invalid")
    if contract_no_egress != {
        "strict": True,
        "allowed_endpoints": allowed,
        "internal_dns_suffixes": suffixes,
        "exact_internal_hosts": exact_hosts,
    }:
        fail("no-egress report differs from normalized deployment semantics")
    normalized_allowed = {
        validate_hostport(value, "no-egress allowlist")
        for value in allowed
        if isinstance(value, str)
    }
    if len(normalized_allowed) != len(allowed):
        fail("bundle no-egress allowlist is unsafe")
    require_exact_endpoint_closure(
        normalized_allowed,
        {item["host"] for item in endpoint_doc["endpoints"] if item["enabled"]},
        destination.split("/", 1)[0],
        host_set,
        suffix_set,
    )
    if any(
        item["enabled"]
        and (
            item["host"] not in normalized_allowed
            or not internal_hostname(item["host"], host_set, suffix_set)
        )
        for item in endpoint_doc["endpoints"]
    ):
        fail("bundle endpoint inventory violates no-egress policy")

    coverage = strict_json_mapping(
        bundle_artifact("coverage-report.json", "coverage report"),
        "coverage report",
        canonical=True,
    )
    only(
        coverage,
        {
            "schema",
            "features",
            "image_use_evidence",
            "uncovered",
            "unowned",
            "unclassified_runtime_inventory",
        },
        "coverage report",
    )
    if coverage != canonical_air_gap_coverage(use_counts, metadata["open_gates"]):
        fail("bundle coverage report is invalid")

    actual_files: set[str] = set()
    actual_dirs: set[str] = set()
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        for name in dirs:
            actual_dirs.add((Path(current) / name).relative_to(root).as_posix())
        for name in files:
            actual_files.add((Path(current) / name).relative_to(root).as_posix())
    if actual_files != expected_files or actual_dirs != expected_dirs:
        fail("bundle contains missing or extra files/directories")
    for relative in actual_files:
        required_mode = 0o700 if relative == "tools/galileoctl" else 0o600
        if stat.S_IMODE(os.lstat(root / relative).st_mode) != required_mode:
            fail("bundle file mode is not exact")
    return metadata


def parse_inventory(
    artifact: Artifact, release_id: str, target_arches: set[str], destination: str
) -> tuple[dict, list[dict]]:
    doc = strict_json_mapping(artifact, "image manifest", canonical=True)
    only(doc, {"schema", "release", "images"}, "image manifest")
    if (
        doc.get("schema") != "galileo-air-gap-image-manifest/v1"
        or doc.get("release") != release_id
    ):
        fail("image manifest schema/release mismatch")
    images = doc.get("images")
    if not isinstance(images, list) or not images:
        fail("image manifest must contain images")
    seen_source: set[str] = set()
    seen_mirror: set[str] = set()
    normalized: list[dict] = []
    for index, item in enumerate(images):
        if not isinstance(item, dict):
            fail(f"images[{index}] must be a mapping")
        only(
            item,
            {
                "source",
                "source_digest",
                "mirror",
                "mirror_digest",
                "archive",
                "archive_sha256",
                "architectures",
                "uses",
                "scan_attestation_file",
                "scan_attestation_sha256",
            },
            f"images[{index}]",
        )
        source = image_reference(
            text(item, "source", f"images[{index}]"), f"images[{index}].source"
        )
        mirror = image_reference(
            text(item, "mirror", f"images[{index}]"), f"images[{index}].mirror"
        )
        validate_source_mirror_roles(source, mirror, destination, f"images[{index}]")
        source_digest = text(item, "source_digest", f"images[{index}]")
        mirror_digest = text(item, "mirror_digest", f"images[{index}]")
        if source in seen_source or mirror in seen_mirror:
            fail("image source and mirror references must be unique")
        seen_source.add(source)
        seen_mirror.add(mirror)
        if not OCI_DIGEST.fullmatch(source_digest) or source_digest != mirror_digest:
            fail("source/mirror digest evidence is invalid or differs")
        arches = item.get("architectures")
        uses = item.get("uses")
        if (
            not isinstance(arches, list)
            or not arches
            or any(not isinstance(value, str) for value in arches)
            or len(arches) != len(set(arches))
            or not set(arches) <= ARCHES
        ):
            fail("image architectures do not cover every target")
        if (
            not isinstance(uses, list)
            or not uses
            or any(not isinstance(value, str) for value in uses)
            or len(uses) != len(set(uses))
            or not set(uses) <= USES
        ):
            fail("image uses are missing or invalid")
        archive = checked(
            text(item, "archive", f"images[{index}]"),
            text(item, "archive_sha256", f"images[{index}]"),
            f"images[{index}] OCI archive",
        )
        identity = oci_identity(archive)
        if source_digest != identity["root_digest"] or set(
            identity["architectures"]
        ) != set(arches):
            fail("OCI archive does not prove the declared root digest/architectures")
        scan = checked(
            text(item, "scan_attestation_file", f"images[{index}]"),
            text(item, "scan_attestation_sha256", f"images[{index}]"),
            f"images[{index}] scan attestation",
        )
        scan_doc = strict_json_mapping(
            scan, f"images[{index}] scan attestation", canonical=True
        )
        only(
            scan_doc,
            {
                "schema",
                "subject",
                "image_digest",
                "passed",
                "scanner",
                "scanner_version",
                "scanned_at",
                "policy",
            },
            f"images[{index}] scan attestation",
        )
        if (
            scan_doc.get("schema") != "galileo-image-scan-attestation/v1"
            or scan_doc.get("subject") != source
            or scan_doc.get("image_digest") != source_digest
            or scan_doc.get("passed") is not True
        ):
            fail("image scan attestation is invalid")
        normalized_scan = {
            "schema": "galileo-image-scan-attestation/v1",
            "subject": source,
            "image_digest": source_digest,
            "passed": True,
            "scanner": text(scan_doc, "scanner", f"images[{index}] scan attestation"),
            "scanner_version": text(
                scan_doc, "scanner_version", f"images[{index}] scan attestation"
            ),
            "scanned_at": timestamp(
                scan_doc.get("scanned_at"), f"images[{index}].scanned_at"
            ),
            "policy": text(scan_doc, "policy", f"images[{index}] scan attestation"),
        }
        if scan_doc != normalized_scan:
            fail("image scan attestation differs from its canonical semantics")
        normalized.append(
            {
                "source": source,
                "source_digest": source_digest,
                "mirror": mirror,
                "mirror_digest": mirror_digest,
                "archive_file": f"images/{index:04d}.oci.tar",
                "archive_sha256": archive.sha256,
                "architectures": sorted(set(arches)),
                "uses": sorted(set(uses)),
                "scan_attestation_file": f"scans/{index:04d}.json",
                "source_scan_attestation_sha256": scan.sha256,
                "_archive": archive,
                "_scan_doc": normalized_scan,
            }
        )
    return doc, normalized


def parse_chart_inventory(
    artifact: Artifact, release_id: str
) -> tuple[dict, set[str], dict[str, int], list[dict]]:
    document = strict_json_mapping(artifact, "chart image inventory", canonical=True)
    only(
        document,
        {"schema", "release", "generated_by", "charts", "images", "use_categories"},
        "chart image inventory",
    )
    if (
        document.get("schema") != "galileo-chart-image-inventory/v1"
        or document.get("release") != release_id
    ):
        fail("chart image inventory schema/release mismatch")
    generated = document.get("generated_by")
    declared_charts = document.get("charts")
    rows = document.get("images")
    evidence = document.get("use_categories")
    if not isinstance(generated, dict):
        fail("chart inventory generation evidence is missing")
    only(generated, {"tool", "stack_bundle_sha256"}, "chart inventory generated_by")
    if (
        generated.get("tool") != "galileo-on-prem-stack-setup"
        or not isinstance(generated.get("stack_bundle_sha256"), str)
        or not HEX64.fullmatch(generated["stack_bundle_sha256"])
    ):
        fail("chart inventory must bind an exact Stack render bundle")
    if not isinstance(declared_charts, list) or not declared_charts:
        fail("chart inventory must bind every exact chart")
    normalized_charts: list[dict] = []
    chart_names: set[str] = set()
    for index, item in enumerate(declared_charts):
        if not isinstance(item, dict) or set(item) != {"name", "version", "sha256"}:
            fail(f"chart inventory charts[{index}] is invalid")
        name = text(item, "name", f"chart inventory charts[{index}]")
        version = text(item, "version", f"chart inventory charts[{index}]")
        digest = text(item, "sha256", f"chart inventory charts[{index}]")
        if (
            not SAFE_NAME.fullmatch(name)
            or not SAFE_VERSION.fullmatch(version)
            or not HEX64.fullmatch(digest)
            or name in chart_names
        ):
            fail("chart inventory chart identity is unsafe or duplicated")
        chart_names.add(name)
        normalized_charts.append({"name": name, "version": version, "sha256": digest})
    if (
        not isinstance(rows, list)
        or not isinstance(evidence, dict)
        or set(evidence) != USES
    ):
        fail(
            "chart image inventory must explicitly account for all image-use categories"
        )
    normalized_evidence: dict[str, dict] = {}
    for use, value in evidence.items():
        if (
            not isinstance(value, dict)
            or set(value) != {"count", "empty_reason"}
            or isinstance(value.get("count"), bool)
            or not isinstance(value.get("count"), int)
            or value["count"] < 0
            or not isinstance(value.get("empty_reason"), str)
        ):
            fail("chart image use-category evidence is invalid")
        reason = value["empty_reason"].strip()
        if reason and SENSITIVE_VALUE.search(reason):
            fail("empty-category evidence contains credential-shaped text")
        if value["count"] == 0 and not reason:
            fail("empty image-use categories require a non-empty reviewed reason")
        if value["count"] > 0 and reason:
            fail(
                "non-empty image-use categories must not carry an empty-category reason"
            )
        normalized_evidence[use] = {"count": value["count"], "empty_reason": reason}
    normalized_rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for index, row in enumerate(rows):
        if (
            not isinstance(row, dict)
            or set(row) != {"source", "use"}
            or row.get("use") not in USES
        ):
            fail(f"chart image inventory row {index} is invalid")
        source = image_reference(
            text(row, "source", f"chart inventory images[{index}]"),
            f"chart inventory images[{index}].source",
        )
        identity = (source, row["use"])
        if identity in seen:
            fail("chart image inventory rows must be unique")
        seen.add(identity)
        normalized_rows.append({"source": source, "use": row["use"]})
    actual_counts = {
        use: sum(row["use"] == use for row in normalized_rows) for use in sorted(USES)
    }
    if actual_counts != {
        use: normalized_evidence[use]["count"] for use in sorted(USES)
    }:
        fail("chart image use-category evidence does not match the inventory rows")
    normalized = {
        "schema": "galileo-chart-image-inventory/v1",
        "release": release_id,
        "generated_by": {
            "tool": "galileo-on-prem-stack-setup",
            "stack_bundle_sha256": generated["stack_bundle_sha256"],
        },
        "charts": sorted(normalized_charts, key=lambda item: item["name"]),
        "images": sorted(normalized_rows, key=lambda row: (row["source"], row["use"])),
        "use_categories": {use: normalized_evidence[use] for use in sorted(USES)},
    }
    if document != normalized:
        fail("chart image inventory is not in canonical semantic order/form")
    return (
        normalized,
        {row["source"] for row in normalized_rows},
        actual_counts,
        normalized["charts"],
    )


def verified_stack_evidence(
    raw: str,
    expected: str,
    evidence_raw: str,
    evidence_expected: str,
) -> tuple[str, list[dict], set[str], dict, dict[str, set[str]]]:
    root = Path(os.path.abspath(Path(raw).expanduser()))
    if not HEX64.fullmatch(expected):
        fail("Stack bundle SHA-256 is invalid")
    try:
        info = os.lstat(root)
    except OSError:
        fail("Stack bundle is unavailable")
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        fail("Stack bundle root must be current-user-owned mode 0700")
    cursor = root.parent
    while True:
        ancestor = os.lstat(cursor)
        if stat.S_ISLNK(ancestor.st_mode) or not stat.S_ISDIR(ancestor.st_mode):
            fail("Stack bundle path has a symlink/non-directory ancestor")
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    stack_script = REPO_ROOT / "skills" / "galileo-on-prem-stack-setup" / "scripts"
    sys.path.insert(0, str(stack_script))
    try:
        from stack_lifecycle import verify_bundle as verify_stack_bundle  # noqa: PLC0415

        manifest, spec = verify_stack_bundle(root)
    except (ImportError, SystemExit, OSError, ValueError):
        fail("Stack bundle failed its canonical offline verifier")
    if manifest.get("bundle_sha256") != expected:
        fail("Stack bundle digest does not match the reviewed value")
    chart_meta = spec.get("stack")
    if (
        not isinstance(chart_meta, dict)
        or not isinstance(chart_meta.get("chart_version"), str)
        or not isinstance(chart_meta.get("chart_sha256"), str)
    ):
        fail("verified Stack bundle lacks exact chart identity")
    evidence_artifact = checked(
        evidence_raw,
        evidence_expected,
        "Stack rendered image inventory evidence",
        private=True,
    )
    evidence = strict_json_mapping(
        evidence_artifact, "Stack rendered image inventory evidence", canonical=True
    )
    only(
        evidence,
        {
            "schema",
            "generated_by",
            "source_bundle_sha256",
            "charts",
            "inputs",
            "redacted_render_sha256",
            "target",
            "created_at",
            "items",
        },
        "Stack rendered image inventory evidence",
    )
    if (
        evidence.get("schema") != "galileo-on-prem-stack-rendered-image-inventory/v1"
        or evidence.get("generated_by") != "galileo-on-prem-stack-setup"
        or evidence.get("source_bundle_sha256") != expected
        or artifact_bytes(evidence_artifact, "Stack rendered image inventory evidence")
        != (json.dumps(evidence, indent=2, sort_keys=True) + "\n").encode()
    ):
        fail("Stack rendered image inventory evidence is not canonical/bundle-bound")
    evidence_charts = evidence.get("charts")
    if not isinstance(evidence_charts, list) or not evidence_charts:
        fail("Stack rendered image evidence has no exact chart set")
    charts: list[dict] = []
    chart_names: set[str] = set()
    release_owners: dict[str, str] = {}
    for index, item in enumerate(evidence_charts):
        if (
            not isinstance(item, dict)
            or set(item) != {"name", "release", "version", "sha256"}
            or item.get("name") in chart_names
            or not SAFE_NAME.fullmatch(str(item.get("name", "")))
            or not SAFE_NAME.fullmatch(str(item.get("release", "")))
            or not SAFE_VERSION.fullmatch(str(item.get("version", "")))
            or not HEX64.fullmatch(str(item.get("sha256", "")))
        ):
            fail(f"Stack rendered image evidence chart {index} is invalid")
        chart_names.add(item["name"])
        if item["release"] in release_owners:
            fail("Stack rendered image evidence chart releases are duplicated")
        release_owners[item["release"]] = item["name"]
        charts.append(
            {
                "name": item["name"],
                "version": item["version"],
                "sha256": item["sha256"],
            }
        )
    expected_stack_chart = {
        "name": "galileo-stack",
        "version": chart_meta["chart_version"],
        "sha256": chart_meta["chart_sha256"],
    }
    expected_charts = [expected_stack_chart]
    ctl = spec.get("galileoctl")
    if isinstance(ctl, dict) and ctl.get("enabled"):
        expected_ctl = {
            "name": "galileoctl",
            "version": ctl.get("chart_version"),
            "sha256": ctl.get("chart_sha256"),
        }
        expected_charts.append(expected_ctl)
    if charts != expected_charts:
        fail("Stack rendered image evidence chart set/order differs from the bundle")
    inputs = evidence.get("inputs")
    target = evidence.get("target")
    ctl_enabled = isinstance(ctl, dict) and ctl.get("enabled") is True
    if (
        not isinstance(inputs, dict)
        or set(inputs)
        != {
            "stack_nonsecret_values_sha256",
            "stack_secret_contract_sha256",
            "galileoctl_nonsecret_values_sha256",
            "galileoctl_secret_contract_sha256",
        }
        or any(
            not isinstance(inputs.get(key), str) or not HEX64.fullmatch(inputs[key])
            for key in (
                "stack_nonsecret_values_sha256",
                "stack_secret_contract_sha256",
            )
        )
        or any(
            (not isinstance(inputs.get(key), str) or not HEX64.fullmatch(inputs[key]))
            if ctl_enabled
            else inputs.get(key) != ""
            for key in (
                "galileoctl_nonsecret_values_sha256",
                "galileoctl_secret_contract_sha256",
            )
        )
        or not isinstance(target, dict)
        or set(target)
        != {
            "context",
            "api_server",
            "ca_sha256",
            "kube_system_uid",
            "namespace",
            "namespace_uid",
        }
        or not isinstance(evidence.get("redacted_render_sha256"), str)
        or not HEX64.fullmatch(evidence["redacted_render_sha256"])
    ):
        fail("Stack rendered image evidence input/target/render binding is invalid")
    if (
        target.get("context") != spec["target"]["kube_context"]
        or target.get("api_server") != spec["target"]["api_server"]
        or target.get("ca_sha256") != spec["target"]["ca_sha256"]
        or target.get("kube_system_uid") != spec["target"]["cluster_uid"]
        or target.get("namespace") != spec["target"]["namespace"]
        or not isinstance(target.get("namespace_uid"), str)
        or not target["namespace_uid"]
    ):
        fail("Stack rendered image evidence target differs from the verified bundle")
    created = datetime.fromisoformat(
        timestamp(
            evidence.get("created_at"), "Stack image evidence created_at"
        ).replace("Z", "+00:00")
    )
    if datetime.now(timezone.utc) - created > timedelta(hours=24):
        fail("Stack rendered image evidence is older than 24 hours")
    sources, source_owners = normalize_rendered_image_rows(
        evidence.get("items"), release_owners, "Stack rendered image evidence items"
    )
    return expected, charts, sources, evidence, source_owners


def verified_stack_endpoint_evidence(
    raw: str,
    expected: str,
    stack_bundle: str,
    image_evidence: dict,
) -> tuple[dict, list[dict]]:
    artifact = checked(raw, expected, "Stack rendered endpoint evidence", private=True)
    document = strict_json_mapping(
        artifact, "Stack rendered endpoint evidence", canonical=True
    )
    only(
        document,
        {
            "schema",
            "generated_by",
            "source_bundle_sha256",
            "charts",
            "inputs",
            "redacted_render_sha256",
            "target",
            "created_at",
            "items",
        },
        "Stack rendered endpoint evidence",
    )
    if (
        document.get("schema") != "galileo-on-prem-stack-rendered-endpoint-inventory/v1"
        or document.get("generated_by") != "galileo-on-prem-stack-setup"
        or artifact_bytes(artifact, "Stack rendered endpoint evidence")
        != canonical_json(document)
    ):
        fail("Stack rendered endpoint evidence is not canonical")
    for key in (
        "source_bundle_sha256",
        "charts",
        "inputs",
        "redacted_render_sha256",
        "target",
        "created_at",
    ):
        if document.get(key) != image_evidence.get(key):
            fail(f"Stack endpoint evidence does not bind image evidence {key}")
    rows = normalize_endpoint_rows(document.get("items"), "Stack endpoint evidence")
    static_hosts = static_endpoint_hosts(Path(os.path.abspath(Path(stack_bundle))))
    if not static_hosts <= {row["host"] for row in rows}:
        fail("Stack endpoint evidence omits a static nonsecret/chart endpoint")
    return document, rows


def verified_child_evidence(
    entry: dict, expected_parent_bundle: str, expected_target: dict
) -> tuple[dict, set[str], dict, dict[str, set[str]], dict, list[dict]]:
    """Verify one standalone child bundle and its canonical rendered-image evidence."""
    only(
        entry,
        {
            "component",
            "bundle",
            "bundle_sha256",
            "evidence_file",
            "evidence_sha256",
            "endpoint_evidence_file",
            "endpoint_evidence_sha256",
        },
        "child image evidence",
    )
    component = text(entry, "component", "child image evidence")
    if component not in {"agent-control", "luna-studio"}:
        fail("child image evidence component is unsupported")
    expected_bundle = text(entry, "bundle_sha256", "child image evidence")
    if not HEX64.fullmatch(expected_bundle):
        fail("child image evidence bundle SHA-256 is invalid")
    bundle = Path(
        os.path.abspath(
            Path(text(entry, "bundle", "child image evidence")).expanduser()
        )
    )
    try:
        bundle_info = os.lstat(bundle)
    except OSError:
        fail(f"{component} bundle is unavailable")
    if (
        stat.S_ISLNK(bundle_info.st_mode)
        or not stat.S_ISDIR(bundle_info.st_mode)
        or bundle_info.st_uid != os.getuid()
        or stat.S_IMODE(bundle_info.st_mode) != 0o700
    ):
        fail(f"{component} bundle root must be current-user-owned mode 0700")
    cursor = bundle.parent
    while True:
        ancestor = os.lstat(cursor)
        if stat.S_ISLNK(ancestor.st_mode) or not stat.S_ISDIR(ancestor.st_mode):
            fail(f"{component} bundle path has a symlink/non-directory ancestor")
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    skill_name = (
        "galileo-on-prem-agent-control-setup"
        if component == "agent-control"
        else "galileo-on-prem-luna-studio-setup"
    )
    module_path = REPO_ROOT / "skills" / skill_name / "scripts" / "render_bundle.py"
    module_spec = importlib.util.spec_from_file_location(
        f"air_gap_{component.replace('-', '_')}_renderer", module_path
    )
    if module_spec is None or module_spec.loader is None:
        fail("child bundle verifier is unavailable")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    try:
        module_spec.loader.exec_module(module)
        metadata = module.validate_bundle(bundle)
    except (OSError, SystemExit, ValueError, AttributeError):
        fail(f"{component} bundle failed its canonical offline verifier")
    finally:
        sys.modules.pop(module_spec.name, None)
    child_target = {
        key: expected_target[key]
        for key in (
            "context",
            "api_server",
            "ca_sha256",
            "kube_system_uid",
            "namespace_uid",
        )
    }
    if (
        metadata.get("bundle_sha256") != expected_bundle
        or metadata.get("ownership") != "standalone"
        or metadata.get("parent_stack", {}).get("bundle_sha256")
        != expected_parent_bundle
        or metadata.get("parent_stack", {}).get("target") != child_target
        or metadata.get("namespace") != expected_target.get("namespace")
    ):
        fail(f"{component} bundle identity/ownership/parent target is invalid")
    evidence_artifact = checked(
        text(entry, "evidence_file", "child image evidence"),
        text(entry, "evidence_sha256", "child image evidence"),
        f"{component} rendered image evidence",
        private=True,
    )
    evidence = strict_json_mapping(
        evidence_artifact, f"{component} rendered image evidence", canonical=True
    )
    only(
        evidence,
        {
            "schema",
            "generated_by",
            "component",
            "source_bundle_sha256",
            "parent_stack_bundle_sha256",
            "chart",
            "inputs",
            "render_inventory_sha256",
            "redacted_render_sha256",
            "target",
            "created_at",
            "items",
        },
        f"{component} rendered image evidence",
    )
    if (
        evidence.get("schema") != "galileo-on-prem-child-rendered-image-inventory/v1"
        or evidence.get("generated_by") != skill_name
        or evidence.get("component") != component
        or evidence.get("source_bundle_sha256") != expected_bundle
        or evidence.get("parent_stack_bundle_sha256") != expected_parent_bundle
        or evidence.get("target") != child_target
        or artifact_bytes(evidence_artifact, f"{component} rendered image evidence")
        != canonical_json(evidence)
    ):
        fail(f"{component} rendered image evidence is not canonical/bundle-bound")
    chart = evidence.get("chart")
    expected_chart = {
        "name": component,
        "release": metadata["release_name"],
        "version": metadata["chart"]["version"],
        "sha256": metadata["chart"]["sha256"],
    }
    if chart != expected_chart:
        fail(f"{component} rendered image evidence chart identity is invalid")
    inputs = evidence.get("inputs")
    overlay_name = (
        "agent-control-overlay.yaml"
        if component == "agent-control"
        else "luna-studio-overlay.yaml"
    )
    expected_inputs = {
        "base_values_sha256": metadata["base_values_sha256"],
        "overlay_values_sha256": secure_file(
            bundle / "values" / overlay_name, f"{component} bundled overlay"
        ).sha256,
    }
    if (
        not isinstance(inputs, dict)
        or set(inputs)
        != {
            "base_values_sha256",
            "overlay_values_sha256",
            "secret_input_contract",
        }
        or any(inputs.get(key) != value for key, value in expected_inputs.items())
        or not isinstance(evidence.get("render_inventory_sha256"), str)
        or not HEX64.fullmatch(evidence["render_inventory_sha256"])
        or not isinstance(evidence.get("redacted_render_sha256"), str)
        or not HEX64.fullmatch(evidence["redacted_render_sha256"])
    ):
        fail(f"{component} rendered image evidence input/render binding is invalid")
    normalize_secret_input_contract(
        inputs.get("secret_input_contract"), f"{component} secret input contract"
    )
    created = datetime.fromisoformat(
        timestamp(
            evidence.get("created_at"), f"{component} image evidence created_at"
        ).replace("Z", "+00:00")
    )
    if datetime.now(timezone.utc) - created > timedelta(hours=24):
        fail(f"{component} rendered image evidence is older than 24 hours")
    sources, owners = normalize_rendered_image_rows(
        evidence.get("items"),
        {metadata["release_name"]: component},
        f"{component} rendered image evidence items",
    )
    endpoint_artifact = checked(
        text(entry, "endpoint_evidence_file", "child endpoint evidence"),
        text(entry, "endpoint_evidence_sha256", "child endpoint evidence"),
        f"{component} rendered endpoint evidence",
        private=True,
    )
    endpoint_document = strict_json_mapping(
        endpoint_artifact, f"{component} rendered endpoint evidence", canonical=True
    )
    only(
        endpoint_document,
        {
            "schema",
            "generated_by",
            "component",
            "source_bundle_sha256",
            "parent_stack_bundle_sha256",
            "chart",
            "inputs",
            "render_inventory_sha256",
            "redacted_render_sha256",
            "target",
            "created_at",
            "items",
        },
        f"{component} rendered endpoint evidence",
    )
    if (
        endpoint_document.get("schema")
        != "galileo-on-prem-child-rendered-endpoint-inventory/v1"
        or endpoint_document.get("generated_by") != skill_name
        or endpoint_document.get("component") != component
        or artifact_bytes(endpoint_artifact, f"{component} rendered endpoint evidence")
        != canonical_json(endpoint_document)
    ):
        fail(f"{component} rendered endpoint evidence is not canonical")
    for key in (
        "component",
        "source_bundle_sha256",
        "parent_stack_bundle_sha256",
        "chart",
        "inputs",
        "render_inventory_sha256",
        "redacted_render_sha256",
        "target",
        "created_at",
    ):
        if endpoint_document.get(key) != evidence.get(key):
            fail(f"{component} endpoint evidence does not bind image evidence {key}")
    endpoint_rows = normalize_endpoint_rows(
        endpoint_document.get("items"), f"{component} endpoint evidence"
    )
    if not static_endpoint_hosts(bundle) <= {row["host"] for row in endpoint_rows}:
        fail(f"{component} endpoint evidence omits a static nonsecret/chart endpoint")
    return expected_chart, sources, evidence, owners, endpoint_document, endpoint_rows


def parse_endpoints(artifact: Artifact, release_id: str) -> dict:
    document = strict_json_mapping(
        artifact, "runtime endpoint inventory", canonical=True
    )
    only(document, {"schema", "release", "endpoints"}, "runtime endpoint inventory")
    if (
        document.get("schema") != "galileo-runtime-endpoints/v1"
        or document.get("release") != release_id
        or not isinstance(document.get("endpoints"), list)
    ):
        fail("runtime endpoint inventory is invalid")
    names: set[str] = set()
    normalized: list[dict] = []
    for index, item in enumerate(document["endpoints"]):
        if (
            not isinstance(item, dict)
            or set(item) != {"name", "host", "purpose", "enabled"}
            or not isinstance(item.get("enabled"), bool)
        ):
            fail(f"runtime endpoint item {index} is invalid")
        name = text(item, "name", f"endpoints[{index}]")
        purpose = text(item, "purpose", f"endpoints[{index}]")
        if (
            len(name) > 128
            or len(purpose) > 512
            or any(ord(character) < 32 for character in name + purpose)
        ):
            fail("runtime endpoint name/purpose is invalid")
        if name in names:
            fail("runtime endpoint names must be unique")
        names.add(name)
        normalized.append(
            {
                "name": name,
                "host": validate_hostport(
                    text(item, "host", f"endpoints[{index}]"),
                    f"endpoints[{index}].host",
                ),
                "purpose": purpose,
                "enabled": item["enabled"],
            }
        )
    return {
        "schema": "galileo-runtime-endpoints/v1",
        "release": release_id,
        "endpoints": sorted(normalized, key=lambda item: item["name"]),
    }


def render(args: argparse.Namespace) -> None:
    spec_artifact = secure_read(args.spec, "air-gap spec")
    spec = mapping(spec_artifact)
    only(
        spec,
        {
            "api_version",
            "galileo",
            "release",
            "registry",
            "artifacts",
            "no_egress",
            "approval",
        },
        "root",
    )
    if spec.get("api_version") != "galileo-on-prem-air-gap-setup/v1":
        fail("unsupported api_version")
    console = origin(args.galileo_console_url)
    galileo = spec.get("galileo")
    if not isinstance(galileo, dict):
        fail("galileo must be a mapping")
    only(galileo, {"console_url"}, "galileo")
    if galileo.get("console_url") and origin(galileo["console_url"]) != console:
        fail("CLI and spec Galileo URLs differ")
    release = spec.get("release")
    registry_spec = spec.get("registry")
    artifacts = spec.get("artifacts")
    no_egress = spec.get("no_egress")
    approval = spec.get("approval")
    for name, value in (
        ("release", release),
        ("registry", registry_spec),
        ("artifacts", artifacts),
        ("no_egress", no_egress),
        ("approval", approval),
    ):
        if not isinstance(value, dict):
            fail(f"{name} must be a mapping")
    only(
        release,
        {"id", "environment", "target_architectures", "optional_components"},
        "release",
    )
    release_id = text(release, "id", "release")
    environment = text(release, "environment", "release")
    if not RELEASE_ID.fullmatch(release_id):
        fail("release.id is unsafe")
    if environment not in {"development", "staging", "production"}:
        fail("release.environment is invalid")
    target_arches_raw = release.get("target_architectures")
    if (
        not isinstance(target_arches_raw, list)
        or not target_arches_raw
        or any(not isinstance(value, str) for value in target_arches_raw)
        or len(target_arches_raw) != len(set(target_arches_raw))
        or not set(target_arches_raw) <= ARCHES
    ):
        fail("target_architectures are invalid")
    target_arches = set(target_arches_raw)
    optional_components = release.get("optional_components")
    if (
        not isinstance(optional_components, dict)
        or set(optional_components) != {"agent-control", "luna-studio"}
        or any(
            value not in {"disabled", "umbrella", "standalone"}
            for value in optional_components.values()
        )
    ):
        fail(
            "release.optional_components must classify Agent Control and Luna Studio ownership"
        )
    only(
        registry_spec,
        {"destination", "internal_dns_suffixes", "exact_internal_hosts"},
        "registry",
    )
    raw_suffixes = registry_spec.get("internal_dns_suffixes")
    raw_hosts = registry_spec.get("exact_internal_hosts")
    if (
        not isinstance(raw_suffixes, list)
        or not isinstance(raw_hosts, list)
        or any(not isinstance(item, str) for item in [*raw_suffixes, *raw_hosts])
    ):
        fail("registry internal DNS policy must use string lists")
    suffixes = {
        validate_dns_suffix(item, "registry internal_dns_suffixes")
        for item in raw_suffixes
    }
    exact_hosts = {
        endpoint_hostname(validate_hostport(item, "registry exact_internal_hosts"))
        for item in raw_hosts
    }
    if any(not item or "." not in item for item in suffixes) or any(
        any(host == public or host.endswith("." + public) for public in PUBLIC_SUFFIXES)
        for host in [*suffixes, *exact_hosts]
    ):
        fail("registry internal DNS policy contains a public/invalid name")
    destination = registry(
        text(registry_spec, "destination", "registry"), exact_hosts, suffixes
    )
    only(
        artifacts,
        {
            "image_manifest_file",
            "image_manifest_sha256",
            "chart_inventory_file",
            "chart_inventory_sha256",
            "stack_bundle",
            "stack_bundle_sha256",
            "stack_image_evidence_file",
            "stack_image_evidence_sha256",
            "stack_endpoint_evidence_file",
            "stack_endpoint_evidence_sha256",
            "child_image_evidence",
            "charts",
            "galileoctl",
            "models",
        },
        "artifacts",
    )
    image_manifest = checked(
        text(artifacts, "image_manifest_file", "artifacts"),
        text(artifacts, "image_manifest_sha256", "artifacts"),
        "CSE image manifest",
    )
    _, images = parse_inventory(image_manifest, release_id, target_arches, destination)
    chart_inventory = checked(
        text(artifacts, "chart_inventory_file", "artifacts"),
        text(artifacts, "chart_inventory_sha256", "artifacts"),
        "chart image inventory",
    )
    chart_doc, chart_sources, use_counts, declared_charts = parse_chart_inventory(
        chart_inventory, release_id
    )
    (
        stack_digest,
        stack_charts,
        stack_sources,
        stack_image_evidence,
        stack_source_owners,
    ) = verified_stack_evidence(
        text(artifacts, "stack_bundle", "artifacts"),
        text(artifacts, "stack_bundle_sha256", "artifacts"),
        text(artifacts, "stack_image_evidence_file", "artifacts"),
        text(artifacts, "stack_image_evidence_sha256", "artifacts"),
    )
    stack_endpoint_evidence, stack_endpoint_rows = verified_stack_endpoint_evidence(
        text(artifacts, "stack_endpoint_evidence_file", "artifacts"),
        text(artifacts, "stack_endpoint_evidence_sha256", "artifacts"),
        text(artifacts, "stack_bundle", "artifacts"),
        stack_image_evidence,
    )
    if chart_doc["generated_by"]["stack_bundle_sha256"] != stack_digest:
        fail("chart inventory is not bound to the verified Stack bundle")
    raw_child_evidence = artifacts.get("child_image_evidence")
    if not isinstance(raw_child_evidence, list):
        fail("artifacts.child_image_evidence must be a list")
    child_components: set[str] = set()
    child_charts: list[dict] = []
    child_sources: set[str] = set()
    child_source_owners: dict[str, set[str]] = {}
    child_evidence_records: list[dict] = []
    for index, entry in enumerate(raw_child_evidence):
        if not isinstance(entry, dict):
            fail(f"child_image_evidence[{index}] must be a mapping")
        component = entry.get("component")
        if component in child_components:
            fail("child image evidence components must be unique")
        (
            chart,
            sources_for_child,
            evidence,
            owners,
            endpoint_evidence,
            endpoint_rows,
        ) = verified_child_evidence(entry, stack_digest, stack_image_evidence["target"])
        child_components.add(component)
        child_charts.append(chart)
        child_sources.update(sources_for_child)
        for source, source_components in owners.items():
            child_source_owners.setdefault(source, set()).update(source_components)
        child_evidence_records.append(
            {
                "component": component,
                "bundle_source": text(
                    entry, "bundle", f"child_image_evidence[{index}]"
                ),
                "bundle_sha256": text(
                    entry, "bundle_sha256", f"child_image_evidence[{index}]"
                ),
                "evidence_source": text(
                    entry, "evidence_file", f"child_image_evidence[{index}]"
                ),
                "evidence_sha256": text(
                    entry, "evidence_sha256", f"child_image_evidence[{index}]"
                ),
                "endpoint_evidence_source": text(
                    entry,
                    "endpoint_evidence_file",
                    f"child_image_evidence[{index}]",
                ),
                "endpoint_evidence_sha256": text(
                    entry,
                    "endpoint_evidence_sha256",
                    f"child_image_evidence[{index}]",
                ),
                "chart": chart,
                "evidence": evidence,
                "endpoint_evidence": endpoint_evidence,
                "endpoint_rows": endpoint_rows,
            }
        )
    require_child_evidence_coverage(optional_components, child_components)
    stack_rendered_mirrors = set(stack_source_owners)
    child_rendered_mirrors = set(child_source_owners)
    rendered_mirror_owners = {
        mirror: set(owners) for mirror, owners in stack_source_owners.items()
    }
    for mirror, owners in child_source_owners.items():
        rendered_mirror_owners.setdefault(mirror, set()).update(owners)
    bind_rendered_mirrors(images, rendered_mirror_owners, "Stack/child rendered images")
    require_image_architecture_coverage(
        [
            stack_image_evidence,
            *(record["evidence"] for record in child_evidence_records),
        ],
        images,
        target_arches,
    )
    stack_sources = {
        item["source"] for item in images if item["mirror"] in stack_rendered_mirrors
    }
    child_sources = {
        item["source"] for item in images if item["mirror"] in child_rendered_mirrors
    }
    combined_charts = sorted(
        [*stack_charts, *child_charts], key=lambda item: item["name"]
    )
    combined_sources = stack_sources | child_sources
    if declared_charts != combined_charts:
        fail("chart inventory chart set differs from Stack plus standalone children")
    if chart_sources != combined_sources:
        fail(
            "chart inventory rows differ from the exact Stack plus standalone child image evidence union"
        )
    image_sources = {item["source"] for item in images}
    if chart_sources != image_sources:
        fail(
            "CSE image manifest must exactly equal Stack plus enabled standalone child sources"
        )
    evidence_digests: dict[str, str] = {}
    for row in stack_image_evidence["items"]:
        evidence_digests[row["image"].rsplit("@", 1)[0]] = row["digest"]
    for record in child_evidence_records:
        for row in record["evidence"]["items"]:
            source = row["image"].rsplit("@", 1)[0]
            previous = evidence_digests.setdefault(source, row["digest"])
            if previous != row["digest"]:
                fail("rendered image evidence disagrees on a shared image digest")
    if any(
        evidence_digests.get(item["mirror"]) != item["mirror_digest"]
        or item["mirror_digest"] != item["source_digest"]
        for item in images
    ):
        fail("CSE image manifest digest differs from exact rendered image evidence")
    for item in chart_doc["images"]:
        rendered = next(x for x in images if x["source"] == item["source"])
        if item["use"] not in rendered["uses"]:
            fail("chart image use classification disagrees with the manifest")
    endpoint_union: list[dict] = [
        *({"owner": "galileo-stack", **row} for row in stack_endpoint_rows),
        *(
            {"owner": record["component"], **row}
            for record in child_evidence_records
            for row in record["endpoint_rows"]
        ),
    ]
    endpoint_union.sort(
        key=lambda item: (
            item["owner"],
            item["host"],
            item["purpose"],
            item["source"],
        )
    )
    endpoint_doc = {
        "schema": "galileo-runtime-endpoints/v1",
        "release": release_id,
        "endpoints": [
            {
                "name": f"{item['owner']}-{index:04d}",
                "host": item["host"],
                "purpose": f"{item['owner']}: {item['purpose']}",
                "enabled": True,
            }
            for index, item in enumerate(endpoint_union)
        ],
    }
    only(
        no_egress,
        {
            "strict",
            "allowed_endpoints",
            "internal_dns_suffixes",
            "exact_internal_hosts",
        },
        "no_egress",
    )
    if not boolean(no_egress, "strict", "no_egress"):
        fail("this skill requires strict no-egress mode")
    allow = no_egress.get("allowed_endpoints")
    if not isinstance(allow, list) or not allow:
        fail("allowed_endpoints must list exact internal hosts")
    allow_values = [
        validate_hostport(item, "allowed_endpoints item")
        if isinstance(item, str)
        else fail("allowed_endpoints items must be strings")
        for item in allow
    ]
    endpoint_suffixes_raw = no_egress.get("internal_dns_suffixes")
    endpoint_hosts_raw = no_egress.get("exact_internal_hosts")
    if (
        not isinstance(endpoint_suffixes_raw, list)
        or not isinstance(endpoint_hosts_raw, list)
        or any(
            not isinstance(item, str)
            for item in [*endpoint_suffixes_raw, *endpoint_hosts_raw]
        )
    ):
        fail("no_egress internal DNS policy must use string lists")
    endpoint_suffixes = {
        validate_dns_suffix(item, "no_egress internal_dns_suffixes")
        for item in endpoint_suffixes_raw
    }
    endpoint_hosts = {
        endpoint_hostname(validate_hostport(item, "no_egress exact_internal_hosts"))
        for item in endpoint_hosts_raw
    }
    if any(not item or "." not in item for item in endpoint_suffixes) or any(
        any(host == public or host.endswith("." + public) for public in PUBLIC_SUFFIXES)
        for host in [*endpoint_suffixes, *endpoint_hosts]
    ):
        fail("no_egress internal DNS policy contains a public/invalid name")
    if len(allow_values) != len(set(allow_values)) or any(
        not internal_hostname(item, endpoint_hosts, endpoint_suffixes)
        for item in allow_values
    ):
        fail("allowed_endpoints must be unique and internal")
    allow_set = set(allow_values)
    registry_host = destination.split("/", 1)[0]
    require_exact_endpoint_closure(
        allow_set,
        {item["host"] for item in endpoint_doc["endpoints"] if item["enabled"]},
        registry_host,
        endpoint_hosts,
        endpoint_suffixes,
    )
    unapproved: list[str] = []
    for item in endpoint_doc["endpoints"]:
        if item["enabled"]:
            host = item["host"]
            if host not in allow_set or not internal_hostname(
                host, endpoint_hosts, endpoint_suffixes
            ):
                unapproved.append(host)
    if unapproved:
        fail("runtime endpoint inventory contains unapproved/public egress")
    charts = artifacts.get("charts")
    models = artifacts.get("models")
    cli = artifacts.get("galileoctl")
    if (
        not isinstance(charts, list)
        or not charts
        or not isinstance(models, list)
        or not isinstance(cli, dict)
    ):
        fail("charts/models/galileoctl contract is invalid")
    copied: list[tuple[str, Artifact]] = []
    chart_meta: list[dict] = []
    chart_names: set[str] = set()
    for index, item in enumerate(charts):
        if not isinstance(item, dict):
            fail("chart entry must be a mapping")
        only(item, {"name", "version", "file", "sha256"}, f"charts[{index}]")
        name = text(item, "name", f"charts[{index}]")
        version = text(item, "version", f"charts[{index}]")
        if (
            not SAFE_NAME.fullmatch(name)
            or not SAFE_VERSION.fullmatch(version)
            or name in chart_names
        ):
            fail("chart name/version is unsafe or duplicated")
        chart_names.add(name)
        artifact = checked(
            text(item, "file", f"charts[{index}]"),
            text(item, "sha256", f"charts[{index}]"),
            f"chart {name}",
        )
        inspection = inspect_helm_chart(artifact, name, version)
        copied.append((f"charts/{index:04d}-{name}.tgz", artifact))
        chart_meta.append(
            {
                "name": name,
                "version": version,
                "file": copied[-1][0],
                "sha256": artifact.sha256,
                "inspection": inspection,
            }
        )
    actual_charts = sorted(
        (
            {"name": item["name"], "version": item["version"], "sha256": item["sha256"]}
            for item in chart_meta
        ),
        key=lambda item: item["name"],
    )
    if actual_charts != declared_charts:
        fail("chart image inventory is not bound to the exact supplied chart set")
    declared_literals = {
        reference
        for item in chart_meta
        for reference in item["inspection"]["declared_image_references"]
    }
    if not declared_literals <= chart_sources:
        fail(
            "literal image references derived from supplied charts are omitted from the chart inventory"
        )
    only(cli, {"version", "file", "sha256", "os", "architecture"}, "galileoctl")
    cli_artifact = checked(
        text(cli, "file", "galileoctl"),
        text(cli, "sha256", "galileoctl"),
        "galileoctl binary",
    )
    cli_version = text(cli, "version", "galileoctl")
    cli_arch = text(cli, "architecture", "galileoctl")
    if (
        not SAFE_VERSION.fullmatch(cli_version)
        or text(cli, "os", "galileoctl") != "linux"
        or cli_arch not in target_arches
        or linux_elf_arch(cli_artifact) != cli_arch
    ):
        fail("galileoctl platform/ELF identity does not match target")
    copied.append(("tools/galileoctl", cli_artifact))
    model_meta: list[dict] = []
    model_names: set[str] = set()
    for index, item in enumerate(models):
        if not isinstance(item, dict):
            fail("model entry must be a mapping")
        only(
            item,
            {"name", "version", "file", "sha256", "architectures"},
            f"models[{index}]",
        )
        arches = item.get("architectures")
        name = text(item, "name", f"models[{index}]")
        version = text(item, "version", f"models[{index}]")
        if (
            not SAFE_NAME.fullmatch(name)
            or not SAFE_VERSION.fullmatch(version)
            or name in model_names
        ):
            fail("model name/version is unsafe or duplicated")
        model_names.add(name)
        if (
            not isinstance(arches, list)
            or not arches
            or any(not isinstance(value, str) for value in arches)
            or len(arches) != len(set(arches))
            or not set(arches) <= ARCHES
            or not target_arches <= set(arches)
        ):
            fail("model architectures do not cover targets")
        artifact = checked(
            text(item, "file", f"models[{index}]"),
            text(item, "sha256", f"models[{index}]"),
            f"model {index}",
        )
        inspection = safe_archive(artifact, f"model {index}")
        if inspection["type"] != "archive":
            fail("model artifacts must be safely inspectable tar/zip archives")
        path = f"models/{index:04d}.bundle"
        copied.append((path, artifact))
        model_meta.append(
            {
                "name": name,
                "version": version,
                "file": path,
                "sha256": artifact.sha256,
                "architectures": sorted(set(arches)),
                "inspection": inspection,
            }
        )
    only(approval, {"cse_reference", "release_manifest_approved"}, "approval")
    cse = text(approval, "cse_reference", "approval")
    if not boolean(approval, "release_manifest_approved", "approval"):
        fail("CSE release manifest approval is required")
    source_hashes = {
        "deployment_spec": spec_artifact.sha256,
        "image_manifest": image_manifest.sha256,
        "chart_inventory": chart_inventory.sha256,
        "stack_bundle": stack_digest,
        "stack_image_evidence": text(
            artifacts, "stack_image_evidence_sha256", "artifacts"
        ),
        "stack_endpoint_evidence": text(
            artifacts, "stack_endpoint_evidence_sha256", "artifacts"
        ),
        "galileoctl": cli_artifact.sha256,
        **{f"chart:{item['name']}": item["sha256"] for item in chart_meta},
        **{f"model:{item['name']}": item["sha256"] for item in model_meta},
        **{f"oci:{item['source']}": item["archive_sha256"] for item in images},
        **{
            f"scan:{item['source']}": item["source_scan_attestation_sha256"]
            for item in images
        },
        **{
            f"child-bundle:{item['component']}": item["bundle_sha256"]
            for item in child_evidence_records
        },
        **{
            f"child-image-evidence:{item['component']}": item["evidence_sha256"]
            for item in child_evidence_records
        },
        **{
            f"child-endpoint-evidence:{item['component']}": item[
                "endpoint_evidence_sha256"
            ]
            for item in child_evidence_records
        },
    }
    contract = canonical_air_gap_contract(
        console=console,
        release_id=release_id,
        environment=environment,
        optional_components=optional_components,
        target_arches=target_arches,
        destination=destination,
        registry_suffixes=suffixes,
        registry_hosts=exact_hosts,
        allowed_endpoints=allow_set,
        endpoint_suffixes=endpoint_suffixes,
        endpoint_hosts=endpoint_hosts,
        cse_reference=cse,
        source_hashes=source_hashes,
    )
    output = Path(os.path.abspath(Path(args.output_dir).expanduser()))
    if (
        output
        in {Path("/"), Path.home(), REPO_ROOT, Path.cwd(), Path(tempfile.gettempdir())}
        or os.path.lexists(output)
        or not output.parent.is_dir()
    ):
        fail("output path is broad, exists, or has no parent")
    parent_info = os.lstat(output.parent)
    if parent_info.st_uid != os.getuid() or stat.S_IMODE(parent_info.st_mode) & 0o022:
        fail("output parent must be current-user-owned and not group/world writable")
    cursor = output.parent
    while True:
        info = os.lstat(cursor)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            fail("output has a symlink/non-directory ancestor")
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    temp = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    temp.chmod(0o700)
    try:
        for dirname in ("charts", "images", "scans", "models", "tools", "evidence"):
            (temp / dirname).mkdir(mode=0o700)
        (temp / "evidence" / "stack-seed-bundle").mkdir(mode=0o700)
        stack_seed_bundle_path = f"evidence/stack-seed-bundle/{stack_digest}"
        copy_verified_bundle(
            Path(
                os.path.abspath(
                    Path(text(artifacts, "stack_bundle", "artifacts")).expanduser()
                )
            ),
            temp / stack_seed_bundle_path,
        )
        if child_evidence_records:
            (temp / "evidence" / "child-bundles").mkdir(mode=0o700)
            (temp / "evidence" / "child-images").mkdir(mode=0o700)
            (temp / "evidence" / "child-endpoints").mkdir(mode=0o700)
        write_json(temp / "normalized-spec.json", contract)
        public_images: list[dict] = []
        for image in images:
            copy_artifact(image["_archive"], temp / image["archive_file"])
            write_json(temp / image["scan_attestation_file"], image["_scan_doc"])
            scan_digest = secure_file(
                temp / image["scan_attestation_file"], "normalized scan attestation"
            ).sha256
            public = {
                key: value for key, value in image.items() if not key.startswith("_")
            }
            public["scan_attestation_sha256"] = scan_digest
            public_images.append(public)
        for relative, artifact in copied:
            copy_artifact(
                artifact,
                temp / relative,
                0o700 if relative == "tools/galileoctl" else 0o600,
            )
        write_json(temp / "evidence" / "chart-image-inventory.json", chart_doc)
        write_json(temp / "evidence" / "runtime-endpoints.json", endpoint_doc)
        write_json(
            temp / "evidence" / "stack-rendered-image-inventory.json",
            stack_image_evidence,
        )
        write_json(
            temp / "evidence" / "stack-rendered-endpoint-inventory.json",
            stack_endpoint_evidence,
        )
        bundled_child_evidence: list[dict] = []
        for record in sorted(
            child_evidence_records, key=lambda item: item["component"]
        ):
            component = record["component"]
            bundle_path = f"evidence/child-bundles/{component}"
            evidence_path = f"evidence/child-images/{component}.json"
            endpoint_evidence_path = f"evidence/child-endpoints/{component}.json"
            copy_verified_bundle(
                Path(os.path.abspath(Path(record["bundle_source"]).expanduser())),
                temp / bundle_path,
            )
            write_json(temp / evidence_path, record["evidence"])
            write_json(temp / endpoint_evidence_path, record["endpoint_evidence"])
            normalized_evidence_digest = secure_file(
                temp / evidence_path, f"normalized {component} image evidence"
            ).sha256
            if normalized_evidence_digest != record["evidence_sha256"]:
                fail(f"{component} image evidence changed during normalization")
            normalized_endpoint_evidence_digest = secure_file(
                temp / endpoint_evidence_path,
                f"normalized {component} endpoint evidence",
            ).sha256
            if (
                normalized_endpoint_evidence_digest
                != record["endpoint_evidence_sha256"]
            ):
                fail(f"{component} endpoint evidence changed during normalization")
            bundled_child_evidence.append(
                {
                    "component": component,
                    "bundle_path": bundle_path,
                    "bundle_sha256": record["bundle_sha256"],
                    "evidence_path": evidence_path,
                    "evidence_sha256": normalized_evidence_digest,
                    "endpoint_evidence_path": endpoint_evidence_path,
                    "endpoint_evidence_sha256": normalized_endpoint_evidence_digest,
                    "chart": record["chart"],
                }
            )
        normalized_chart_sha256 = secure_file(
            temp / "evidence" / "chart-image-inventory.json",
            "normalized chart inventory",
        ).sha256
        normalized_endpoint_sha256 = secure_file(
            temp / "evidence" / "runtime-endpoints.json",
            "normalized endpoint inventory",
        ).sha256
        normalized_stack_image_sha256 = secure_file(
            temp / "evidence" / "stack-rendered-image-inventory.json",
            "normalized Stack rendered image inventory",
        ).sha256
        normalized_stack_endpoint_sha256 = secure_file(
            temp / "evidence" / "stack-rendered-endpoint-inventory.json",
            "normalized Stack rendered endpoint inventory",
        ).sha256
        stack_images = [
            dict(image) for image in public_images if image["source"] in stack_sources
        ]
        child_images = [
            dict(image) for image in public_images if image["source"] in child_sources
        ]
        write_json(
            temp / "image-manifest.json",
            {
                "schema": "galileo-air-gap-image-manifest/v1",
                "release": release_id,
                "images": public_images,
            },
        )
        open_gates = completion_gates(model_meta)
        write_json(
            temp / "no-egress-report.json",
            {
                "schema": "galileo-no-egress-report/v1",
                "release": release_id,
                "strict": False,
                "allowed_endpoints": sorted(allow_set),
                "internal_dns_suffixes": sorted(endpoint_suffixes),
                "exact_internal_hosts": sorted(endpoint_hosts),
                "unapproved_endpoints": [],
                "unvalidated_gates": open_gates,
            },
        )
        write_json(
            temp / "coverage-report.json",
            canonical_air_gap_coverage(use_counts, open_gates),
        )
        metadata = {
            "schema": SCHEMA,
            "bundle_sha256": "PENDING",
            "release_id": release_id,
            "environment": environment,
            "galileo_console_url": console,
            "target_architectures": sorted(target_arches),
            "registry_destination": destination,
            "registry_internal_dns_suffixes": sorted(suffixes),
            "registry_exact_internal_hosts": sorted(exact_hosts),
            "internal_dns_suffixes": sorted(endpoint_suffixes),
            "exact_internal_hosts": sorted(endpoint_hosts),
            "cse_reference": cse,
            "source_spec_sha256": spec_artifact.sha256,
            "source_image_manifest_sha256": image_manifest.sha256,
            "source_chart_inventory_sha256": chart_inventory.sha256,
            "chart_inventory_sha256": normalized_chart_sha256,
            "stack_bundle_sha256": stack_digest,
            "stack_seed_bundle_path": stack_seed_bundle_path,
            "source_stack_image_evidence_sha256": text(
                artifacts, "stack_image_evidence_sha256", "artifacts"
            ),
            "stack_image_evidence_sha256": normalized_stack_image_sha256,
            "source_stack_endpoint_evidence_sha256": text(
                artifacts, "stack_endpoint_evidence_sha256", "artifacts"
            ),
            "stack_endpoint_evidence_sha256": normalized_stack_endpoint_sha256,
            "stack_seed": {
                "evidence_sha256": normalized_stack_image_sha256,
                "source_bundle_sha256": stack_image_evidence["source_bundle_sha256"],
                "charts": stack_image_evidence["charts"],
                "inputs": stack_image_evidence["inputs"],
                "redacted_render_sha256": stack_image_evidence[
                    "redacted_render_sha256"
                ],
                "target": stack_image_evidence["target"],
                "items": stack_image_evidence["items"],
            },
            "stack_endpoint_seed": {
                "evidence_sha256": normalized_stack_endpoint_sha256,
                "source_bundle_sha256": stack_endpoint_evidence["source_bundle_sha256"],
                "charts": stack_endpoint_evidence["charts"],
                "inputs": stack_endpoint_evidence["inputs"],
                "redacted_render_sha256": stack_endpoint_evidence[
                    "redacted_render_sha256"
                ],
                "target": stack_endpoint_evidence["target"],
                "items": stack_endpoint_evidence["items"],
            },
            "endpoint_inventory_sha256": normalized_endpoint_sha256,
            "source_hashes": source_hashes,
            "optional_components": {
                key: optional_components[key] for key in sorted(optional_components)
            },
            "child_image_evidence": bundled_child_evidence,
            "charts": chart_meta,
            "galileoctl": {
                "version": cli_version,
                "file": "tools/galileoctl",
                "sha256": cli_artifact.sha256,
                "os": "linux",
                "architecture": cli_arch,
            },
            "models": model_meta,
            "images": public_images,
            "stack_images": stack_images,
            "child_images": child_images,
            "open_gates": open_gates,
            "registry_push_execution": "galileo-cse-operator-handoff-only",
        }
        write_json(temp / "metadata.json", metadata)
        pending_manifest = manifest_payload(temp)
        identity = hashlib.sha256(pending_manifest).hexdigest()
        metadata["bundle_sha256"] = identity
        replace_json(temp / "metadata.json", metadata)
        final_metadata_digest = hashlib.sha256(
            (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode()
        ).hexdigest()
        final_lines = []
        for line in pending_manifest.decode("ascii").splitlines():
            parts = line.split("  ", 2)
            if parts[2] == "metadata.json":
                parts[0] = final_metadata_digest
            final_lines.append("  ".join(parts))
        write(temp / "MANIFEST.sha256", "\n".join(final_lines) + "\n")
        write(temp / "BUNDLE.sha256", identity + "\n")
        fsync_directory(temp)
        verify_bundle(temp)
        if os.path.lexists(output):
            fail("output appeared during render")
        os.rename(temp, output)
        fsync_directory(output.parent)
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    print(
        json.dumps(
            {
                "status": "rendered-incomplete",
                "bundle": str(output),
                "images": len(images),
                "unapproved_endpoints": [],
                "open_gates": open_gates,
            },
            sort_keys=True,
        )
    )


def minimal_env(
    auth_file: Path,
) -> tuple[dict[str, str], tempfile.TemporaryDirectory[str]]:
    holder = tempfile.TemporaryDirectory(prefix="galileo-oci-")
    root = Path(holder.name)
    root.chmod(0o700)
    config = root / "config"
    cache = root / "cache"
    data = root / "data"
    runtime = root / "runtime"
    for directory in (config, cache, data, runtime):
        directory.mkdir(mode=0o700)
    auth_copy = root / "auth.json"
    write(
        auth_copy,
        artifact_bytes(
            secure_read(auth_file, "registry auth", private=True, limit=1024 * 1024),
            "registry auth",
        ),
    )
    env = {
        "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin",
        "XDG_CONFIG_HOME": str(config),
        "XDG_CACHE_HOME": str(cache),
        "XDG_DATA_HOME": str(data),
        "XDG_RUNTIME_DIR": str(runtime),
        "TMPDIR": str(root),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "REGISTRY_AUTH_FILE": str(auth_copy),
    }
    for key in ("SSL_CERT_FILE", "SSL_CERT_DIR"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env, holder


def push(args: argparse.Namespace, bundle: Path, metadata: dict) -> None:
    fail(
        "registry push is handoff-only: this skill performs no registry write; "
        "use the exact bundle, digest inventory, and CSE approval in an "
        "operator-controlled session that rejects tag overwrite"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Galileo air-gap supply chain")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--render", action="store_true")
    modes.add_argument("--verify", action="store_true")
    modes.add_argument("--verify-no-egress", action="store_true")
    modes.add_argument("--push-registry", action="store_true")
    parser.add_argument("--spec")
    parser.add_argument("--output-dir")
    parser.add_argument("--bundle")
    parser.add_argument("--galileo-console-url")
    parser.add_argument("--registry-auth-file")
    parser.add_argument("--approval-file")
    parser.add_argument("--result-file")
    parser.add_argument("--accept-registry-write", action="store_true")
    args = parser.parse_args()
    if args.push_registry:
        fail(
            "registry push is handoff-only: this skill performs no registry write; "
            "use the exact bundle, digest inventory, and CSE approval in an "
            "operator-controlled session that rejects tag overwrite"
        )
    if args.render:
        if not all((args.spec, args.output_dir, args.galileo_console_url)):
            fail("render requires --spec, --output-dir, and --galileo-console-url")
        render(args)
        return 0
    if not args.bundle:
        fail("mode requires --bundle")
    bundle = Path(os.path.abspath(Path(args.bundle).expanduser()))
    metadata = verify_bundle(bundle)
    if (
        not args.galileo_console_url
        or origin(args.galileo_console_url) != metadata["galileo_console_url"]
    ):
        fail("mode requires the exact bundle-bound --galileo-console-url")
    if args.push_registry:
        push(args, bundle, metadata)
    elif args.verify_no_egress:
        report = strict_json_mapping(
            secure_read(bundle / "no-egress-report.json", "no-egress report"),
            "no-egress report",
            canonical=True,
        )
        if "endpoint_rewrite_evidence_missing" in metadata["open_gates"]:
            fail(
                "endpoint_rewrite_evidence_missing: Stack does not emit canonical "
                "scheme+host[:port] source-to-mirror and seed-to-final rewrite evidence"
            )
        if report.get("strict") is not True or report.get("unapproved_endpoints") != []:
            fail("no-egress report is not clean")
        print(
            json.dumps(
                {"status": "no-egress-verified", "unapproved_endpoints": []},
                sort_keys=True,
            )
        )
    else:
        if "stack_model_evidence_missing" in metadata["open_gates"]:
            fail(
                "stack_model_evidence_missing: model archives are not bound to "
                "rendered mounts/configuration and an in-workload checksum verifier"
            )
        if "endpoint_rewrite_evidence_missing" in metadata["open_gates"]:
            fail(
                "endpoint_rewrite_evidence_missing: Stack does not emit canonical "
                "scheme+host[:port] source-to-mirror and seed-to-final rewrite evidence"
            )
        print(
            json.dumps(
                {
                    "status": "verified",
                    "bundle_sha256": metadata["bundle_sha256"],
                    "images": len(metadata["images"]),
                },
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
