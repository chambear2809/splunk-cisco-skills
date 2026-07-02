#!/usr/bin/env python3
"""Verify an immutable rendered bundle and safely copy reviewed external input."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Optional, Tuple


class VerifyError(ValueError):
    pass


READ_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
)
MAX_JSON_BYTES = 8 * 1024 * 1024
REQUIRED_FILES = {
    "sok": {
        "README.md",
        "metadata.json",
        "namespace.yaml",
        "apply.sh",
        "bundle-verify.py",
        "crds-install.sh",
        "preflight.sh",
        "server-dry-run.sh",
        "compatibility-check.py",
        "verify-cluster.sh",
        "operator-values.yaml",
        "enterprise-values.yaml",
        "helm-install-operator.sh",
        "helm-install-enterprise.sh",
        "status.sh",
    },
    "pod": {
        "README.md",
        "metadata.json",
        "cluster-config.yaml",
        "bundle-verify.py",
        "preflight.sh",
        "deploy.sh",
        "status-workers.sh",
        "status.sh",
        "get-creds.sh",
        "web-docs.sh",
        "wait-ready.sh",
        "diagnostics.sh",
        "pod-artifacts.py",
        "pod-inputs.py",
    },
}


def digest_fd(
    fd: int, destination_fd: Optional[int] = None
) -> Tuple[str, os.stat_result, os.stat_result]:
    before = os.fstat(fd)
    digest = hashlib.sha256()
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
        if destination_fd is not None:
            view = memoryview(chunk)
            while view:
                written = os.write(destination_fd, view)
                if written <= 0:
                    raise OSError("short write while copying reviewed input")
                view = view[written:]
    return digest.hexdigest(), before, os.fstat(fd)


def stable_identity(item: os.stat_result) -> tuple[int, int, int, int, int]:
    return item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns


def hash_nofollow(path: Path, expected_mode: Optional[int] = None) -> str:
    try:
        fd = os.open(path, READ_FLAGS)
    except OSError as error:
        raise VerifyError(f"cannot open reviewed file {path}: {error}") from error
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise VerifyError(f"reviewed input is not a singly linked regular file: {path}")
        mode = stat.S_IMODE(opened.st_mode)
        if expected_mode is not None and (
            opened.st_uid != os.geteuid() or mode != expected_mode
        ):
            raise VerifyError(
                f"tracked file owner/mode differs for {path}: "
                f"uid={opened.st_uid}, mode={mode:#o}, expected={expected_mode:#o}"
            )
        if expected_mode is None and mode & 0o022:
            raise VerifyError(f"reviewed external input is group/world-writable: {path}")
        digest, before, after = digest_fd(fd)
        if stable_identity(opened) != stable_identity(before) or stable_identity(before) != stable_identity(after):
            raise VerifyError(f"reviewed input changed while hashing: {path}")
        return digest
    finally:
        os.close(fd)


def read_json_nofollow(path: Path) -> dict:
    try:
        fd = os.open(path, READ_FLAGS)
    except OSError as error:
        raise VerifyError(f"cannot open bundle JSON {path}: {error}") from error
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise VerifyError(
                f"bundle JSON is not a singly linked regular file: {path}"
            )
        if before.st_uid != os.geteuid() or stat.S_IMODE(before.st_mode) != 0o600:
            raise VerifyError(f"bundle JSON must be owner-controlled mode 0600: {path}")
        if before.st_size > MAX_JSON_BYTES:
            raise VerifyError(f"bundle JSON exceeds {MAX_JSON_BYTES} bytes: {path}")
        chunks = []
        total = 0
        while True:
            chunk = os.read(fd, min(1024 * 1024, MAX_JSON_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_JSON_BYTES:
                raise VerifyError(
                    f"bundle JSON exceeds {MAX_JSON_BYTES} bytes: {path}"
                )
        after = os.fstat(fd)
        if stable_identity(before) != stable_identity(after):
            raise VerifyError(f"bundle JSON changed while reading: {path}")
        try:
            value = json.loads(b"".join(chunks).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise VerifyError(f"bundle JSON is invalid: {path}: {error}") from error
        if not isinstance(value, dict):
            raise VerifyError(f"bundle JSON root must be an object: {path}")
        return value
    finally:
        os.close(fd)


def load_manifest(root: Path, target: str) -> dict:
    if target not in REQUIRED_FILES:
        raise VerifyError(f"unsupported bundle target: {target}")
    if root.is_symlink() or not root.is_dir():
        raise VerifyError("bundle root must be a real directory")
    root = root.resolve()
    root_stat = root.stat()
    if root_stat.st_uid != os.geteuid() or stat.S_IMODE(root_stat.st_mode) != 0o700:
        raise VerifyError("bundle root must be owned by the current user with mode 0700")
    manifest_path = root / "bundle-manifest.json"
    manifest = read_json_nofollow(manifest_path)
    metadata = read_json_nofollow(root / "metadata.json")
    if metadata.get("target") != target or manifest.get("algorithm") != "sha256":
        raise VerifyError("bundle target or digest algorithm differs")
    files = manifest.get("files")
    modes = manifest.get("modes")
    external = manifest.get("external_files")
    if (
        not isinstance(files, dict)
        or not isinstance(modes, dict)
        or not isinstance(external, dict)
        or set(modes) != set(files)
    ):
        raise VerifyError("bundle manifest inventories are invalid")
    missing = sorted(REQUIRED_FILES[target] - set(files))
    if missing:
        raise VerifyError(
            "required files are not integrity-tracked: " + ", ".join(missing)
        )
    allowed_untracked = {"kubeconfig"} if target == "sok" and metadata.get("eks_cluster_name") else set()
    for candidate in root.iterdir():
        if candidate.name == "bundle-manifest.json" or candidate.name in files:
            continue
        if (
            candidate.name in allowed_untracked
            and candidate.is_file()
            and not candidate.is_symlink()
        ):
            candidate_stat = candidate.stat()
            if (
                candidate_stat.st_uid != os.geteuid()
                or candidate_stat.st_nlink != 1
                or stat.S_IMODE(candidate_stat.st_mode) != 0o600
            ):
                raise VerifyError(
                    f"runtime kubeconfig must be owner-controlled mode 0600: {candidate}"
                )
            continue
        raise VerifyError(f"untracked bundle entry is present: {candidate.name}")
    for relative, expected in files.items():
        rel = Path(relative)
        if rel.is_absolute() or ".." in rel.parts or len(rel.parts) != 1:
            raise VerifyError(f"unsafe tracked path: {relative}")
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise VerifyError(f"invalid tracked digest: {relative}")
        expected_mode = modes.get(relative)
        if expected_mode not in {0o400, 0o500, 0o600, 0o700}:
            raise VerifyError(f"invalid tracked mode: {relative}")
        if hash_nofollow(root / rel, expected_mode) != expected:
            raise VerifyError(f"tracked bundle file drifted: {relative}")
    for raw, expected in external.items():
        path = Path(raw)
        if not path.is_absolute() or not re.fullmatch(r"[0-9a-f]{64}", str(expected)):
            raise VerifyError(f"invalid external manifest entry: {raw}")
        if hash_nofollow(path) != expected:
            raise VerifyError(f"reviewed external file drifted: {raw}")
    return manifest


def copy_external(root: Path, source: Path, destination: Path) -> None:
    manifest = load_manifest(root, "sok")
    canonical = str(source.expanduser().resolve())
    expected = manifest["external_files"].get(canonical)
    if not expected:
        raise VerifyError(f"external source is not integrity-tracked: {canonical}")
    source_fd = os.open(source, READ_FLAGS)
    try:
        before = os.fstat(source_fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise VerifyError("external source is not a singly linked regular file")
        output_fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
        try:
            digest, first, after = digest_fd(source_fd, output_fd)
            os.fsync(output_fd)
        finally:
            os.close(output_fd)
        if stable_identity(first) != stable_identity(after) or digest != expected:
            destination.unlink(missing_ok=True)
            raise VerifyError("external source changed or no longer matches review")
        destination.chmod(0o400)
    finally:
        os.close(source_fd)


def main() -> int:
    try:
        if len(sys.argv) == 4 and sys.argv[1] == "verify":
            load_manifest(Path(sys.argv[2]), sys.argv[3])
        elif len(sys.argv) == 5 and sys.argv[1] == "copy-external":
            copy_external(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
        else:
            raise VerifyError(
                "usage: bundle-verify.py verify BUNDLE TARGET | "
                "copy-external BUNDLE SOURCE DESTINATION"
            )
    except (VerifyError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
