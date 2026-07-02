#!/usr/bin/env python3
"""Validate local Splunk POD packages and ingress cryptographic material."""

from __future__ import annotations

import configparser
import datetime as dt
import bz2
import email.utils
import gzip
import hashlib
import json
import lzma
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


MAX_ARCHIVE_MEMBERS = 50_000
MAX_ARCHIVE_BYTES = 8 * 1024 * 1024 * 1024
MAX_TAR_TRAILER_BYTES = 1024 * 1024

POD_104_ITSI_SOURCE_ROOTS = {
    "DA-ITSI-APPSERVER",
    "DA-ITSI-DATABASE",
    "DA-ITSI-EUEM",
    "DA-ITSI-LB",
    "DA-ITSI-OS",
    "DA-ITSI-STORAGE",
    "DA-ITSI-VIRTUALIZATION",
    "DA-ITSI-WEBSERVER",
    "SA-ITOA",
    "SA-ITSI-AI-Summarization",
    "SA-ITSI-AT-Recommendations",
    "SA-ITSI-ATAD",
    "SA-ITSI-AlertCorrelation",
    "SA-ITSI-CustomModuleViz",
    "SA-ITSI-DriftDetection",
    "SA-ITSI-Licensechecker",
    "SA-ITSI-MetricAD",
    "SA-IndexCreation",
    "SA-UserAccess",
    "itsi",
}
POD_104_ITSI_SEARCH_ROOTS = (POD_104_ITSI_SOURCE_ROOTS - {"SA-ITSI-Licensechecker"}) | {
    "jdk"
}


class ArtifactError(ValueError):
    """A local artifact is unsafe, malformed, incomplete, or mismatched."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class AppRoot:
    root: str
    digest: str
    paths: frozenset[str]
    small_files: dict[str, bytes]
    file_info: dict[str, tuple[int, int, bytes]]


def _safe_member_path(name: str) -> tuple[str, ...]:
    if (
        not name
        or name.startswith("/")
        or "\\" in name
        or any(ord(character) < 32 or ord(character) == 127 for character in name)
    ):
        raise ArtifactError(f"unsafe archive member path: {name!r}")
    parts = tuple(part for part in PurePosixPath(name).parts if part not in {"", "."})
    if not parts or any(part == ".." for part in parts):
        raise ArtifactError(f"unsafe archive member path: {name!r}")
    if len(name.encode("utf-8")) > 4096 or any(
        len(part.encode("utf-8")) > 255 for part in parts
    ):
        raise ArtifactError(f"archive member path exceeds portable limits: {name!r}")
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,127}", parts[0]):
        raise ArtifactError(f"nonportable Splunk app root: {parts[0]!r}")
    return parts


def _safe_link_target(root: str, member_parts: tuple[str, ...], target: str) -> None:
    if (
        not target
        or target.startswith("/")
        or "\\" in target
        or any(ord(character) < 32 or ord(character) == 127 for character in target)
    ):
        raise ArtifactError(f"unsafe archive link target: {target!r}")
    if len(target.encode("utf-8")) > 4096 or any(
        len(part.encode("utf-8")) > 255 for part in PurePosixPath(target).parts
    ):
        raise ArtifactError(f"archive link target exceeds portable limits: {target!r}")
    base = list(member_parts[:-1])
    for part in PurePosixPath(target).parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not base:
                raise ArtifactError(f"archive link escapes app root: {target!r}")
            base.pop()
        else:
            base.append(part)
    if not base or base[0] != root:
        raise ArtifactError(f"archive link escapes app root: {target!r}")


def _tar_number(raw: bytes, label: str) -> int:
    if raw and raw[0] & 0x80:
        return int.from_bytes(raw, "big") & ((1 << (len(raw) * 8 - 1)) - 1)
    cleaned = raw.rstrip(b"\0 ").lstrip(b" ") or b"0"
    try:
        return int(cleaned, 8)
    except ValueError as error:
        raise ArtifactError(f"invalid tar {label} field") from error


def verify_tar_stream(path: Path) -> int:
    """Read the complete tar stream, verifying headers, padding, and terminator."""
    with path.open("rb") as raw_stream:
        magic = raw_stream.read(6)
    opener = open
    if magic.startswith(b"\x1f\x8b"):
        opener = gzip.open
    elif magic.startswith(b"BZh"):
        opener = bz2.open
    elif magic.startswith(b"\xfd7zXZ\x00"):
        opener = lzma.open
    total = 0
    members = 0
    visible_members = 0
    try:
        with opener(path, "rb") as stream:
            while True:
                header = stream.read(512)
                total += len(header)
                if len(header) != 512:
                    raise ArtifactError("truncated tar header or missing end markers")
                if header == b"\0" * 512:
                    second = stream.read(512)
                    total += len(second)
                    if second != b"\0" * 512:
                        raise ArtifactError("tar archive has only one zero end block")
                    trailer_bytes = 0
                    while True:
                        trailer = stream.read(1024 * 1024)
                        if not trailer:
                            break
                        total += len(trailer)
                        trailer_bytes += len(trailer)
                        if trailer_bytes > MAX_TAR_TRAILER_BYTES:
                            raise ArtifactError("tar archive has excessive zero padding")
                        if trailer.strip(b"\0"):
                            raise ArtifactError("tar archive has nonzero trailing data")
                    break
                members += 1
                if members > MAX_ARCHIVE_MEMBERS:
                    raise ArtifactError(
                        f"archive exceeds {MAX_ARCHIVE_MEMBERS} members: {path}"
                    )
                stored_checksum = _tar_number(header[148:156], "checksum")
                computed_checksum = sum(header[:148]) + (8 * 32) + sum(header[156:])
                if stored_checksum != computed_checksum:
                    raise ArtifactError("tar header checksum mismatch")
                for field, label in (
                    (header[100:108], "mode"),
                    (header[108:116], "uid"),
                    (header[116:124], "gid"),
                    (header[136:148], "mtime"),
                ):
                    _tar_number(field, label)
                type_flag = header[156:157]
                if type_flag not in b"\0\x30\x31\x32\x33\x34\x35\x36\x37xgLKS":
                    raise ArtifactError(f"unsupported tar type flag: {type_flag!r}")
                if type_flag not in {b"x", b"g", b"L", b"K"}:
                    visible_members += 1
                size = _tar_number(header[124:136], "size")
                padded = ((size + 511) // 512) * 512
                if size > MAX_ARCHIVE_BYTES or total + padded > MAX_ARCHIVE_BYTES + 64 * 1024 * 1024:
                    raise ArtifactError(
                        f"archive expands beyond {MAX_ARCHIVE_BYTES} bytes: {path}"
                    )
                remaining = padded
                while remaining:
                    chunk = stream.read(min(remaining, 1024 * 1024))
                    if not chunk:
                        raise ArtifactError("truncated tar member data")
                    remaining -= len(chunk)
                    total += len(chunk)
    except (EOFError, OSError, lzma.LZMAError, tarfile.TarError, zlib.error) as error:
        raise ArtifactError(f"invalid compressed tar stream {path}: {error}") from error
    return visible_members


def inspect_archive(path: Path) -> dict[str, AppRoot]:
    """Inspect a tar app without extraction and return canonical app manifests."""

    path = path.expanduser().resolve()
    if not path.is_file():
        raise ArtifactError(f"app archive is missing: {path}")
    expected_member_count = verify_tar_stream(path)
    records: dict[str, list[bytes]] = {}
    paths: dict[str, set[str]] = {}
    small_files: dict[str, dict[str, bytes]] = {}
    file_info: dict[str, dict[str, tuple[int, int, bytes]]] = {}
    seen: set[str] = set()
    member_types: dict[str, str] = {}
    regular_members: set[str] = set()
    hardlinks: list[tuple[str, str]] = []
    regular_counts: dict[str, int] = {}
    expanded_bytes = 0
    captured_bytes = 0
    try:
        archive = tarfile.open(path, mode="r:*")
    except (tarfile.TarError, OSError) as error:
        raise ArtifactError(f"invalid POD app archive {path}: {error}") from error
    observed_member_count = 0
    with archive:
        for member_count, member in enumerate(archive, 1):
            observed_member_count = member_count
            if member_count > MAX_ARCHIVE_MEMBERS:
                raise ArtifactError(
                    f"archive exceeds {MAX_ARCHIVE_MEMBERS} members: {path}"
                )
            parts = _safe_member_path(member.name)
            if member.mode & 0o6000:
                raise ArtifactError(
                    f"setuid/setgid archive mode is forbidden: {member.name!r}"
                )
            normalized = "/".join(parts)
            lexical = member.name.rstrip("/") if member.isdir() else member.name
            if (
                lexical != normalized
                or (not member.isdir() and member.name.endswith("/"))
            ):
                raise ArtifactError(
                    f"noncanonical archive member spelling: {member.name!r}"
                )
            if normalized in seen:
                raise ArtifactError(f"duplicate archive member {normalized!r}: {path}")
            seen.add(normalized)
            root = parts[0]
            relative = "/".join(parts[1:])
            records.setdefault(root, [])
            paths.setdefault(root, set())
            small_files.setdefault(root, {})
            file_info.setdefault(root, {})
            regular_counts.setdefault(root, 0)
            if member.isdir():
                member_types[normalized] = "directory"
                records[root].append(
                    f"directory\0{relative}\0{member.mode & 0o7777:o}".encode()
                )
                paths[root].add(relative)
                continue
            if member.isdev() or member.isfifo():
                raise ArtifactError(
                    f"special file is forbidden in app archive: {normalized}"
                )
            if member.issym():
                member_types[normalized] = "symlink"
                _safe_link_target(root, parts, member.linkname)
                record = f"symlink\0{relative}\0{member.mode & 0o7777:o}\0{member.linkname}".encode()
                records[root].append(record)
                paths[root].add(relative)
                continue
            if member.islnk():
                member_types[normalized] = "hardlink"
                target_parts = _safe_member_path(member.linkname)
                if target_parts[0] != root:
                    raise ArtifactError(
                        f"archive hardlink crosses app roots: {normalized} -> {member.linkname}"
                    )
                target = "/".join(target_parts)
                hardlinks.append((normalized, target))
                records[root].append(
                    f"hardlink\0{relative}\0{member.mode & 0o7777:o}\0{target}".encode()
                )
                paths[root].add(relative)
                continue
            if not member.isfile():
                raise ArtifactError(f"unsupported archive member type: {normalized}")
            member_types[normalized] = "file"
            expanded_bytes += member.size
            if expanded_bytes > MAX_ARCHIVE_BYTES:
                raise ArtifactError(
                    f"archive expands beyond {MAX_ARCHIVE_BYTES} bytes: {path}"
                )
            handle = archive.extractfile(member)
            if handle is None:
                raise ArtifactError(f"cannot read archive member: {normalized}")
            digest = hashlib.sha256()
            captured = bytearray()
            capture = relative in {
                "default/app.conf",
                "default/indexes.conf",
                "local/indexes.conf",
                "metadata/default.meta",
                "release",
                "bin/java",
                "bin/javac",
            } or relative.endswith(("/release", "/bin/java", "/bin/javac"))
            if capture and member.size > 1024 * 1024:
                raise ArtifactError(
                    f"validation metadata file is too large: {normalized}"
                )
            if capture and captured_bytes + member.size > 16 * 1024 * 1024:
                raise ArtifactError(
                    f"archive has excessive validation metadata: {path}"
                )
            with handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
                    if capture and len(captured) <= 1024 * 1024:
                        captured.extend(chunk)
            record = f"file\0{relative}\0{member.mode & 0o7777:o}\0{member.size}\0{digest.hexdigest()}".encode()
            records[root].append(record)
            paths[root].add(relative)
            regular_members.add(normalized)
            regular_counts[root] += 1
            file_info[root][relative] = (
                member.mode & 0o7777,
                member.size,
                bytes(captured[:4096]),
            )
            if capture and len(captured) <= 1024 * 1024:
                small_files[root][relative] = bytes(captured)
                captured_bytes += len(captured)
    if observed_member_count != expected_member_count:
        raise ArtifactError(
            f"tar member inventory is inconsistent: stream={expected_member_count}, "
            f"parser={observed_member_count} in {path}"
        )
    for normalized, member_type in member_types.items():
        parts = normalized.split("/")
        for index in range(1, len(parts)):
            ancestor = "/".join(parts[:index])
            ancestor_type = member_types.get(ancestor)
            if ancestor_type is not None and ancestor_type != "directory":
                raise ArtifactError(
                    f"archive {member_type} {normalized!r} is nested beneath "
                    f"non-directory {ancestor_type} {ancestor!r}: {path}"
                )
    for member, target in hardlinks:
        if target not in regular_members:
            raise ArtifactError(
                f"archive hardlink target is not a regular member: {member} -> {target}"
            )
    if not records:
        raise ArtifactError(f"archive has no app roots: {path}")
    result = {}
    for root, root_records in records.items():
        if regular_counts[root] < 1:
            raise ArtifactError(f"app root contains no regular files: {root} in {path}")
        canonical = hashlib.sha256(b"\n".join(sorted(root_records))).hexdigest()
        app = AppRoot(
            root,
            canonical,
            frozenset(paths[root]),
            small_files[root],
            file_info[root],
        )
        _validate_package_id(path, app)
        result[root] = app
    return result


def _validate_package_id(path: Path, app: AppRoot) -> None:
    raw = app.small_files.get("default/app.conf")
    if raw is None:
        raise ArtifactError(f"app root lacks default/app.conf: {app.root} in {path}")
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read_string(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, configparser.Error) as error:
        raise ArtifactError(
            f"invalid {app.root}/default/app.conf in {path}: {error}"
        ) from error
    package_id = parser.get("package", "id", fallback="").strip()
    if package_id and package_id != app.root:
        raise ArtifactError(
            f"package id {package_id!r} does not match archive root {app.root!r}: {path}"
        )


def _app_version(app: AppRoot) -> str:
    raw = app.small_files.get("default/app.conf", b"")
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read_string(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, configparser.Error) as error:
        raise ArtifactError(f"cannot parse version for app root {app.root}: {error}") from error
    return parser.get("launcher", "version", fallback="").strip()


def _single_roots(paths: list[str], option: str) -> dict[str, AppRoot]:
    roots: dict[str, AppRoot] = {}
    for raw_path in paths:
        archive_roots = inspect_archive(Path(raw_path))
        if len(archive_roots) != 1:
            raise ArtifactError(
                f"{option} archive must contain exactly one top-level app root: {raw_path}"
            )
        root, app = next(iter(archive_roots.items()))
        if root in roots:
            raise ArtifactError(f"duplicate internal app root {root!r} in {option}")
        roots[root] = app
    return roots


def validate_pod_index_apps(metadata: dict) -> dict:
    """Enforce Splunk POD's custom-index contract on indexer-scoped apps."""
    roots = _single_roots(metadata.get("indexer_apps", []), "--indexer-apps")
    checked_stanzas = 0
    for app in roots.values():
        merged: dict[str, dict[str, str]] = {}
        found = False
        for relative in ("default/indexes.conf", "local/indexes.conf"):
            raw = app.small_files.get(relative)
            if raw is None:
                continue
            found = True
            parser = configparser.ConfigParser(interpolation=None, strict=True)
            parser.optionxform = str.lower
            try:
                parser.read_string(raw.decode("utf-8-sig"), source=f"{app.root}/{relative}")
            except (UnicodeDecodeError, configparser.Error) as error:
                raise ArtifactError(
                    f"invalid {app.root}/{relative}: {error}"
                ) from error
            for section in parser.sections():
                merged.setdefault(section, {}).update(
                    dict(parser.items(section, raw=True))
                )
        if not found:
            continue
        defaults = merged.get("default", {})
        for section, values in merged.items():
            lowered = section.lower()
            for forbidden in ("repfactor", "remotepath"):
                if forbidden in values:
                    raise ArtifactError(
                        f"POD index app {app.root} must not set {forbidden} in "
                        f"indexes.conf stanza [{section}]"
                    )
            if lowered == "default" or lowered.startswith("volume:"):
                continue
            missing = []
            for required in ("homepath", "coldpath", "thawedpath"):
                value = values.get(required, "").strip()
                if not value:
                    value = defaults.get(required, "").strip()
                if not value:
                    missing.append(required)
            if missing:
                raise ArtifactError(
                    f"POD index app {app.root} stanza [{section}] is missing "
                    f"required {', '.join(missing)}"
                )
            checked_stanzas += 1
    return {"pod_index_stanzas_checked": checked_stanzas}


def _validate_jdk(app: AppRoot) -> None:
    required = {"default/app.conf", "metadata/default.meta"}
    missing = sorted(required - app.paths)
    java = ["bin/java"] if "bin/java" in app.paths else []
    javac = ["bin/javac"] if "bin/javac" in app.paths else []
    releases = ["release"] if "release" in app.paths else []
    if missing or not java or not javac or not releases:
        raise ArtifactError(
            "jdk app must contain default/app.conf, metadata/default.meta, "
            "OpenJDK release metadata, bin/java, and bin/javac"
        )
    app_conf = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        app_conf.read_string(
            app.small_files["default/app.conf"].decode("utf-8-sig"),
            source="jdk/default/app.conf",
        )
    except (UnicodeDecodeError, configparser.Error) as error:
        raise ArtifactError(f"invalid jdk/default/app.conf: {error}") from error
    if (
        app_conf.get("install", "state", fallback="").strip().lower() != "enabled"
        or app_conf.get("install", "is_configured", fallback="").strip().lower()
        != "true"
        or app_conf.get("ui", "show_in_nav", fallback="").strip().lower()
        != "false"
    ):
        raise ArtifactError(
            "jdk/default/app.conf must enable and configure the app while hiding it "
            "from navigation"
        )

    try:
        meta_text = app.small_files["metadata/default.meta"].decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ArtifactError("jdk/metadata/default.meta is not UTF-8") from error

    def meta_stanza(name: str) -> dict[str, str]:
        match = re.search(
            rf"(?ms)^\[{re.escape(name)}\]\s*$\n(.*?)(?=^\[[^\n]*\]\s*$|\Z)",
            meta_text,
        )
        if not match:
            return {}
        values = {}
        for line in match.group(1).splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", ";")):
                continue
            if "=" not in stripped:
                raise ArtifactError(
                    f"invalid jdk/metadata/default.meta line in [{name}]"
                )
            key, value = stripped.split("=", 1)
            values[key.strip().lower()] = re.sub(r"\s+", " ", value.strip())
        return values

    root_meta = meta_stanza("")
    saved_meta = meta_stanza("savedsearches")
    governance_meta = meta_stanza("governance")
    if (
        root_meta.get("access") != "read : [ * ], write : [ admin ]"
        or root_meta.get("export", "").lower() != "system"
        or saved_meta.get("owner", "").lower() != "admin"
        or governance_meta.get("access") != "read : [ * ], write : [ * ]"
    ):
        raise ArtifactError(
            "jdk/metadata/default.meta does not match the documented POD ITSI "
            "access, export, owner, and governance settings"
        )
    release_values = [app.small_files.get(path, b"") for path in releases]
    if not any(
        re.search(rb'JAVA_VERSION\s*=\s*["\']?17(?:[.\-_"\']|$)', value)
        for value in release_values
    ):
        raise ArtifactError("jdk app does not identify an OpenJDK 17 runtime")
    for path in (*java, *javac):
        mode, size, header = app.file_info.get(path, (0, 0, b""))
        if not mode & 0o111 or size < 8192:
            raise ArtifactError(f"jdk executable is empty or not executable: {path}")
        if header[:4] != b"\x7fELF" or len(header) < 20 or header[4] != 2:
            raise ArtifactError(f"jdk executable is not a 64-bit Linux ELF file: {path}")
        byte_order = "little" if header[5] == 1 else "big" if header[5] == 2 else ""
        machine = int.from_bytes(header[18:20], byte_order) if byte_order else 0
        if machine != 62:
            raise ArtifactError(f"jdk executable is not x86-64 as required by POD: {path}")
        elf_type = int.from_bytes(header[16:18], byte_order) if byte_order else 0
        elf_version = int.from_bytes(header[20:24], byte_order) if byte_order else 0
        program_offset = int.from_bytes(header[32:40], byte_order) if byte_order else 0
        header_size = int.from_bytes(header[52:54], byte_order) if byte_order else 0
        program_entry_size = int.from_bytes(header[54:56], byte_order) if byte_order else 0
        program_count = int.from_bytes(header[56:58], byte_order) if byte_order else 0
        if (
            elf_type not in {2, 3}
            or elf_version != 1
            or header_size != 64
            or program_entry_size < 56
            or program_count < 1
            or program_offset < 64
            or program_offset + program_entry_size * program_count > size
        ):
            raise ArtifactError(f"jdk executable has an invalid ELF program header: {path}")
        table_end = program_offset + program_entry_size * program_count
        if table_end > len(header):
            raise ArtifactError(f"jdk ELF program-header table is not inspectable: {path}")
        executable_load = False
        for index in range(program_count):
            start = program_offset + index * program_entry_size
            entry = header[start : start + program_entry_size]
            segment_type = int.from_bytes(entry[0:4], byte_order)
            flags = int.from_bytes(entry[4:8], byte_order)
            offset = int.from_bytes(entry[8:16], byte_order)
            file_size = int.from_bytes(entry[32:40], byte_order)
            memory_size = int.from_bytes(entry[40:48], byte_order)
            if offset + file_size > size or memory_size < file_size:
                raise ArtifactError(f"jdk executable has an invalid ELF segment: {path}")
            if segment_type == 1 and flags & 0x1 and file_size > 0:
                executable_load = True
        if not executable_load:
            raise ArtifactError(f"jdk executable has no executable PT_LOAD segment: {path}")


def validate_itsi(metadata: dict) -> dict:
    source_path = metadata.get("itsi_source_bundle")
    if not source_path:
        raise ArtifactError("ITSI profile requires itsi_source_bundle")
    expected_sha256 = (metadata.get("itsi_source_sha256") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ArtifactError("ITSI profile requires a reviewed itsi_source_sha256")
    actual_sha256 = file_sha256(Path(source_path))
    if actual_sha256 != expected_sha256:
        raise ArtifactError("ITSI source bundle does not match its reviewed SHA-256")
    source = inspect_archive(Path(source_path))
    source_roots = set(source)
    if source_roots != POD_104_ITSI_SOURCE_ROOTS:
        missing = sorted(POD_104_ITSI_SOURCE_ROOTS - source_roots)
        extra = sorted(source_roots - POD_104_ITSI_SOURCE_ROOTS)
        raise ArtifactError(
            "ITSI source bundle root inventory does not match the POD 10.4 baseline; "
            f"missing={missing}, extra={extra}"
        )
    if _app_version(source["itsi"]) != "4.21.2":
        raise ArtifactError("POD 10.4 requires an ITSI 4.21.2 source bundle")
    search = _single_roots(metadata.get("itsi_apps", []), "--itsi-apps")
    if set(search) != POD_104_ITSI_SEARCH_ROOTS:
        missing = sorted(POD_104_ITSI_SEARCH_ROOTS - set(search))
        extra = sorted(set(search) - POD_104_ITSI_SEARCH_ROOTS)
        raise ArtifactError(
            f"ITSI search package inventory is incomplete; missing={missing}, extra={extra}"
        )
    _validate_jdk(search["jdk"])
    expected_jdk_sha256 = (metadata.get("itsi_jdk_sha256") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_jdk_sha256):
        raise ArtifactError("ITSI profile requires a reviewed itsi_jdk_sha256")
    jdk_archives = []
    for raw_path in metadata.get("itsi_apps", []):
        if "jdk" in inspect_archive(Path(raw_path)):
            jdk_archives.append(Path(raw_path).expanduser().resolve())
    if len(jdk_archives) != 1:
        raise ArtifactError("ITSI profile requires exactly one reviewed jdk archive")
    actual_jdk_sha256 = file_sha256(jdk_archives[0])
    if actual_jdk_sha256 != expected_jdk_sha256:
        raise ArtifactError("ITSI JDK archive does not match its reviewed SHA-256")
    for root in POD_104_ITSI_SOURCE_ROOTS - {"SA-ITSI-Licensechecker"}:
        if search[root].digest != source[root].digest:
            raise ArtifactError(f"repacked ITSI app differs from source bundle: {root}")
    indexer = _single_roots(metadata.get("indexer_apps", []), "--indexer-apps")
    license_manager = _single_roots(
        metadata.get("license_manager_apps", []), "--license-manager-apps"
    )
    for root, scope in (
        ("SA-IndexCreation", indexer),
        ("SA-ITSI-Licensechecker", license_manager),
        ("SA-UserAccess", license_manager),
    ):
        if root not in scope:
            raise ArtifactError(
                f"required ITSI app is missing from its POD scope: {root}"
            )
        if scope[root].digest != source[root].digest:
            raise ArtifactError(
                f"POD-scoped ITSI app differs from source bundle: {root}"
            )
    return {
        "itsi_source_bundle": str(Path(source_path).resolve()),
        "itsi_source_sha256": actual_sha256,
        "itsi_jdk_sha256": actual_jdk_sha256,
        "itsi_version": "4.21.2",
        "itsi_source_roots": sorted(source_roots),
        "itsi_search_roots": sorted(search),
    }


def validate_es(metadata: dict) -> dict:
    indexer = _single_roots(metadata.get("indexer_apps", []), "--indexer-apps")
    if "Splunk_TA_ForIndexers" not in indexer:
        raise ArtifactError(
            "ES indexer packages do not contain internal root Splunk_TA_ForIndexers"
        )
    premium_roots = _single_roots(metadata.get("premium_apps", []), "--premium-apps")
    if "SplunkEnterpriseSecuritySuite" not in premium_roots:
        raise ArtifactError(
            "ES premium packages do not contain internal root SplunkEnterpriseSecuritySuite"
        )
    es_version = _app_version(premium_roots["SplunkEnterpriseSecuritySuite"])
    ta_version = _app_version(indexer["Splunk_TA_ForIndexers"])
    supported_versions = {"8.3.0", "8.4.1", "8.5.1"}
    if es_version not in supported_versions:
        raise ArtifactError(
            f"ES {es_version or '<missing>'} is not in the POD/Enterprise 10.4 "
            f"reviewed set: {sorted(supported_versions)}"
        )
    if ta_version != es_version:
        raise ArtifactError(
            f"Splunk_TA_ForIndexers {ta_version or '<missing>'} does not match ES {es_version}"
        )
    return {
        "es_indexer_roots": sorted(indexer),
        "es_premium_roots": sorted(premium_roots),
        "es_version": es_version,
    }


def _run(command: list[str], *, stdin: bytes | None = None) -> bytes:
    try:
        result = subprocess.run(
            command,
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ArtifactError(f"cannot run {' '.join(command)}: {error}") from error
    if result.returncode:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise ArtifactError(f"{' '.join(command)} failed: {detail}")
    return result.stdout


def validate_tls(metadata: dict) -> dict:
    certificate = metadata.get("ingress_certificate_file")
    private_key = metadata.get("ingress_private_key_file")
    if not certificate and not private_key:
        return {}
    if not certificate or not private_key:
        raise ArtifactError(
            "ingress certificate and private key must be supplied together"
        )
    openssl = shutil.which("openssl")
    if not openssl:
        raise ArtifactError("openssl is required to validate POD TLS material")
    cert_path = Path(certificate).expanduser().resolve()
    key_path = Path(private_key).expanduser().resolve()
    key_bytes = key_path.read_bytes()
    key_pattern = re.compile(
        rb"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----\s+.+?\s+"
        rb"-----END (?:RSA |EC )?PRIVATE KEY-----",
        flags=re.DOTALL,
    )
    key_blocks = list(key_pattern.finditer(key_bytes))
    if len(key_blocks) != 1 or key_pattern.sub(b"", key_bytes).strip():
        raise ArtifactError(
            "ingress private-key file must contain exactly one supported PRIVATE KEY "
            "PEM block and whitespace"
        )
    def certificate_only_pem(pem_path: Path, label: str) -> list[bytes]:
        data = pem_path.read_bytes()
        pattern = re.compile(
            rb"-----BEGIN CERTIFICATE-----\s+.+?\s+-----END CERTIFICATE-----",
            flags=re.DOTALL,
        )
        matches = list(pattern.finditer(data))
        residue = pattern.sub(b"", data)
        if residue.strip():
            raise ArtifactError(
                f"{label} must contain only CERTIFICATE PEM blocks and whitespace"
            )
        return [match.group(0) for match in matches]

    blocks = certificate_only_pem(cert_path, "ingress certificate file")
    if not blocks:
        raise ArtifactError("ingress certificate file contains no PEM certificates")
    for block in blocks:
        text = _run([openssl, "x509", "-noout", "-text"], stdin=block).decode(
            "utf-8", "replace"
        )
        algorithms = re.findall(r"Signature Algorithm:\s*([^\s]+)", text)
        if not algorithms or any(
            "sha1" in algorithm.lower() or "md5" in algorithm.lower()
            for algorithm in algorithms
        ):
            raise ArtifactError(
                "ingress certificate chain uses an unsupported signature"
            )
        dates = _run([openssl, "x509", "-noout", "-dates"], stdin=block).decode(
            "utf-8", "replace"
        )
        date_values = dict(
            line.split("=", 1) for line in dates.splitlines() if "=" in line
        )
        try:
            not_before = email.utils.parsedate_to_datetime(date_values["notBefore"])
            not_after = email.utils.parsedate_to_datetime(date_values["notAfter"])
        except (KeyError, TypeError, ValueError) as error:
            raise ArtifactError("cannot parse ingress certificate validity") from error
        now = dt.datetime.now(dt.timezone.utc)
        if not_before > now:
            raise ArtifactError("ingress certificate chain is not yet valid")
        if not_after < now + dt.timedelta(days=30):
            raise ArtifactError(
                "every ingress certificate must remain valid for at least 30 days"
            )
    cert_pub = _run([openssl, "x509", "-pubkey", "-noout"], stdin=blocks[0])
    public_key_text = _run(
        [openssl, "pkey", "-pubin", "-text", "-noout"], stdin=cert_pub
    ).decode("utf-8", "replace")
    rsa_bits = re.search(r"Public-Key:\s*\((\d+) bit\)", public_key_text)
    ec_curve = re.search(r"ASN1 OID:\s*([^\s]+)", public_key_text)
    if rsa_bits:
        if int(rsa_bits.group(1)) < 2048:
            raise ArtifactError("POD ingress RSA key must be at least 2048 bits")
    elif ec_curve:
        if ec_curve.group(1) not in {"prime256v1", "secp384r1", "secp521r1"}:
            raise ArtifactError("POD ingress certificate uses an unsupported EC curve")
    else:
        raise ArtifactError("POD ingress certificate uses an unsupported public-key type")
    cert_pub_der = _run([openssl, "pkey", "-pubin", "-outform", "DER"], stdin=cert_pub)
    key_pub_der = _run(
        [
            openssl,
            "pkey",
            "-in",
            str(key_path),
            "-pubout",
            "-outform",
            "DER",
            "-passin",
            "pass:",
        ]
    )
    if cert_pub_der != key_pub_der:
        raise ArtifactError("ingress certificate and private key do not match")
    san_output = _run(
        [openssl, "x509", "-noout", "-ext", "subjectAltName"], stdin=blocks[0]
    ).decode("utf-8", "replace")
    wildcard_domains = {
        match.lower().rstrip(".")
        for match in re.findall(r"DNS:\*\.([A-Za-z0-9.-]+)", san_output)
    }
    if not wildcard_domains:
        raise ArtifactError("POD ingress certificate needs a wildcard DNS SAN")
    asserted_domain = (metadata.get("ingress_domain") or "").lower().rstrip(".")
    if asserted_domain and asserted_domain not in wildcard_domains:
        raise ArtifactError(
            f"asserted ingress domain {asserted_domain!r} is not covered by a wildcard SAN"
        )
    leaf_text = _run([openssl, "x509", "-noout", "-text"], stdin=blocks[0]).decode(
        "utf-8", "replace"
    )
    if not re.search(
        r"X509v3 Basic Constraints:[^\n]*\n\s*CA:FALSE\b", leaf_text
    ):
        raise ArtifactError("POD ingress leaf certificate must have CA:FALSE")
    if not re.search(
        r"X509v3 Extended Key Usage:[^\n]*\n\s*[^\n]*(?:TLS Web Server Authentication|1\.3\.6\.1\.5\.5\.7\.3\.1)",
        leaf_text,
    ):
        raise ArtifactError("POD ingress leaf certificate requires serverAuth EKU")
    key_usage = re.search(r"X509v3 Key Usage:[^\n]*\n\s*([^\n]+)", leaf_text)
    if not key_usage or not re.search(
        r"Digital Signature|Key Encipherment|Key Agreement", key_usage.group(1)
    ):
        raise ArtifactError(
            "POD ingress leaf certificate has no TLS-compatible Key Usage"
        )
    representative_host = f"splunk.{asserted_domain or sorted(wildcard_domains)[0]}"
    _run(
        [openssl, "x509", "-noout", "-checkhost", representative_host],
        stdin=blocks[0],
    )
    ca_file = metadata.get("ingress_ca_file")
    if not ca_file:
        raise ArtifactError("POD ingress validation requires an explicit CA trust bundle")
    ca_path = Path(ca_file).expanduser().resolve()
    ca_blocks = certificate_only_pem(ca_path, "ingress CA bundle")
    if not ca_blocks:
        raise ArtifactError("ingress CA bundle contains no PEM certificates")
    if len(ca_blocks) > 5:
        raise ArtifactError("ingress CA bundle must be a minimal set of at most 5 anchors")
    now = dt.datetime.now(dt.timezone.utc)
    for ca_block in ca_blocks:
        ca_text = _run([openssl, "x509", "-noout", "-text"], stdin=ca_block).decode(
            "utf-8", "replace"
        )
        if not re.search(
            r"X509v3 Basic Constraints:[^\n]*\n\s*CA:TRUE\b", ca_text
        ):
            raise ArtifactError("every ingress CA-bundle certificate must have CA:TRUE")
        ca_usage = re.search(r"X509v3 Key Usage:[^\n]*\n\s*([^\n]+)", ca_text)
        if not ca_usage or "Certificate Sign" not in ca_usage.group(1):
            raise ArtifactError("every ingress CA certificate requires keyCertSign")
        algorithms = re.findall(r"Signature Algorithm:\s*([^\s]+)", ca_text)
        if not algorithms or any(
            "sha1" in algorithm.lower() or "md5" in algorithm.lower()
            for algorithm in algorithms
        ):
            raise ArtifactError("ingress CA bundle uses an unsupported signature")
        ca_pub = _run([openssl, "x509", "-pubkey", "-noout"], stdin=ca_block)
        ca_public_key_text = _run(
            [openssl, "pkey", "-pubin", "-text", "-noout"], stdin=ca_pub
        ).decode("utf-8", "replace")
        ca_rsa_bits = re.search(
            r"Public-Key:\s*\((\d+) bit\)", ca_public_key_text
        )
        ca_ec_curve = re.search(r"ASN1 OID:\s*([^\s]+)", ca_public_key_text)
        if ca_rsa_bits:
            if int(ca_rsa_bits.group(1)) < 2048:
                raise ArtifactError(
                    "every POD ingress CA RSA key must be at least 2048 bits"
                )
        elif ca_ec_curve:
            if ca_ec_curve.group(1) not in {
                "prime256v1",
                "secp384r1",
                "secp521r1",
            }:
                raise ArtifactError(
                    "POD ingress CA uses an unsupported EC curve"
                )
        else:
            raise ArtifactError("POD ingress CA uses an unsupported public-key type")
        ca_dates = _run(
            [openssl, "x509", "-noout", "-dates"], stdin=ca_block
        ).decode("utf-8", "replace")
        ca_date_values = dict(
            line.split("=", 1) for line in ca_dates.splitlines() if "=" in line
        )
        try:
            ca_not_before = email.utils.parsedate_to_datetime(
                ca_date_values["notBefore"]
            )
            ca_not_after = email.utils.parsedate_to_datetime(ca_date_values["notAfter"])
        except (KeyError, TypeError, ValueError) as error:
            raise ArtifactError("cannot parse ingress CA certificate validity") from error
        if ca_not_before > now or ca_not_after < now + dt.timedelta(days=30):
            raise ArtifactError(
                "every ingress CA certificate must be currently valid for at least 30 days"
            )
    with tempfile.TemporaryDirectory() as tmpdir:
        leaf = Path(tmpdir) / "leaf.pem"
        chain = Path(tmpdir) / "chain.pem"
        leaf.write_bytes(blocks[0] + b"\n")
        chain.write_bytes(b"\n".join(blocks[1:]) + b"\n")
        command = [
            openssl,
            "verify",
            "-purpose",
            "sslserver",
            "-verify_hostname",
            representative_host,
            "-CAfile",
            str(ca_path),
        ]
        if len(blocks) > 1:
            command.extend(["-untrusted", str(chain)])
        command.append(str(leaf))
        _run(command)
    return {
        "ingress_wildcard_domains": sorted(wildcard_domains),
        "ingress_trust_verified": True,
    }


def validate_ssh_key(metadata: dict) -> dict:
    raw_path = metadata.get("ssh_private_key_file")
    if not raw_path or str(raw_path).startswith("/path/to/"):
        return {}
    path = Path(raw_path).expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise ArtifactError("POD SSH private key is missing or unsafe")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise ArtifactError("POD SSH private key permissions must deny group/other access")
    ssh_keygen = shutil.which("ssh-keygen")
    if not ssh_keygen:
        raise ArtifactError("ssh-keygen is required to validate the POD SSH private key")
    public = _run(
        [ssh_keygen, "-y", "-P", "", "-f", str(path)]
    ).decode("ascii", "replace").strip()
    if not re.fullmatch(
        r"(?:ssh-(?:rsa|ed25519)|ecdsa-sha2-nistp(?:256|384|521))\s+"
        r"[A-Za-z0-9+/=]+(?:\s+[^\r\n]+)?",
        public,
    ):
        raise ArtifactError("POD SSH private key has an unsupported public-key type")
    fingerprint = _run([ssh_keygen, "-lf", str(path)]).decode(
        "ascii", "replace"
    ).strip()
    fingerprint_match = re.match(r"^(\d+)\s+\S+.*\((RSA|ED25519|ECDSA)\)\s*$", fingerprint)
    if not fingerprint_match:
        raise ArtifactError("cannot determine POD SSH private-key strength")
    if fingerprint_match.group(2) == "RSA" and int(fingerprint_match.group(1)) < 2048:
        raise ArtifactError("POD SSH RSA private key must be at least 2048 bits")
    return {"ssh_private_key_verified": True}


def validate_metadata(metadata: dict) -> dict:
    report = {"target": "pod", "pod_profile": metadata.get("pod_profile")}
    profile = metadata.get("pod_profile", "")
    # Securely parse every provided app archive, even when it has no
    # product-specific inventory rule.
    for field in (
        "indexer_apps",
        "cluster_manager_apps",
        "search_apps",
        "search_deployer_apps",
        "standalone_apps",
        "premium_apps",
        "itsi_apps",
        "license_manager_apps",
    ):
        seen_roots = {}
        for raw_path in metadata.get(field, []):
            roots = inspect_archive(Path(raw_path))
            if len(roots) != 1:
                raise ArtifactError(
                    f"{field} archive must contain exactly one top-level app root: {raw_path}"
                )
            root = next(iter(roots))
            if root in seen_roots:
                raise ArtifactError(
                    f"duplicate internal app root {root!r} in {field}: "
                    f"{seen_roots[root]} and {raw_path}"
                )
            seen_roots[root] = raw_path
    if profile.endswith("-es"):
        report.update(validate_es(metadata))
    if profile.endswith("-itsi"):
        report.update(validate_itsi(metadata))
    report.update(validate_pod_index_apps(metadata))
    report.update(validate_ssh_key(metadata))
    report.update(validate_tls(metadata))
    return report


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: {Path(sys.argv[0]).name} METADATA.json", file=sys.stderr)
        return 2
    try:
        metadata = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        report = validate_metadata(metadata)
    except (
        ArtifactError,
        EOFError,
        OSError,
        json.JSONDecodeError,
        tarfile.TarError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
