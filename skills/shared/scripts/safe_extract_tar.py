#!/usr/bin/env python3
"""Validate and safely extract a tar archive into a new private directory.

The extractor deliberately does not use ``TarFile.extractall``.  It validates
the complete member graph first, writes directories and regular files before
links, and creates links only after proving that their targets remain below the
destination.  The destination must not already exist.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import sys
import tarfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO


class UnsafeArchive(ValueError):
    """Raised when an archive violates the extraction contract."""


def fail(message: str) -> None:
    raise UnsafeArchive(message)


def relative_member_path(value: str, *, label: str) -> PurePosixPath:
    if (
        not value
        or "\\" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or (len(value) >= 2 and value[0].isalpha() and value[1] == ":")
    ):
        fail(f"{label} is empty or contains unsupported characters: {value!r}")
    path = PurePosixPath(value)
    if (
        not path.parts
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        fail(f"{label} is not a safe relative path: {value!r}")
    return path


def relative_link_path(value: str, *, label: str) -> PurePosixPath:
    if (
        not value
        or "\\" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or (len(value) >= 2 and value[0].isalpha() and value[1] == ":")
    ):
        fail(f"{label} is empty or contains unsupported characters: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute():
        fail(f"{label} must not be absolute: {value!r}")
    return path


def descendant(root: Path, candidate: Path, *, label: str) -> Path:
    root = root.resolve(strict=False)
    candidate = candidate.resolve(strict=False)
    try:
        common = Path(os.path.commonpath((root, candidate)))
    except ValueError as exc:
        fail(f"{label} is on an incompatible path: {exc}")
    if common != root or candidate == root:
        fail(f"{label} escapes the destination: {candidate}")
    return candidate


def normalized_link_target(
    destination: Path,
    member: tarfile.TarInfo,
    member_path: PurePosixPath,
) -> Path:
    link_path = relative_link_path(member.linkname, label=f"link target for {member.name!r}")
    if member.issym():
        candidate = destination.joinpath(*member_path.parent.parts, *link_path.parts)
    else:
        # Tar hard-link names are archive-root relative, unlike symlink names.
        candidate = destination.joinpath(*link_path.parts)
    member_root = destination / member_path.parts[0]
    return descendant(member_root, candidate, label=f"link target for {member.name!r}")


def inspect_archive(
    archive_stream: BinaryIO,
    destination: Path,
    expected_roots: set[str],
    require_exact_roots: bool,
) -> tuple[list[tarfile.TarInfo], set[str]]:
    seen: set[PurePosixPath] = set()
    link_paths: set[PurePosixPath] = set()
    roots: set[str] = set()

    archive_stream.seek(0)
    with tarfile.open(fileobj=archive_stream, mode="r:*") as archive:
        members = archive.getmembers()

    if not members:
        fail("archive contains no members")

    for member in members:
        member_path = relative_member_path(member.name, label="archive member")
        if member_path in seen:
            fail(f"archive contains a duplicate member path: {member.name!r}")
        seen.add(member_path)
        roots.add(member_path.parts[0])
        descendant(
            destination,
            destination.joinpath(*member_path.parts),
            label=f"archive member {member.name!r}",
        )
        if not (member.isdir() or member.isreg() or member.issym() or member.islnk()):
            fail(f"archive member uses a special or unsupported file type: {member.name!r}")
        if member.issym() or member.islnk():
            link_paths.add(member_path)
            normalized_link_target(destination, member, member_path)

    for member_path in seen:
        for parent in member_path.parents:
            if parent == PurePosixPath("."):
                break
            if parent in link_paths:
                fail(f"archive member is nested below a link: {member_path!s}")

    if expected_roots:
        missing = expected_roots - roots
        if missing:
            fail(f"archive is missing expected top-level root(s): {', '.join(sorted(missing))}")
        if require_exact_roots and roots != expected_roots:
            unexpected = roots - expected_roots
            fail(f"archive has unexpected top-level root(s): {', '.join(sorted(unexpected))}")

    return members, roots


def safe_mode(member: tarfile.TarInfo, *, directory: bool) -> int:
    fallback = 0o755 if directory else 0o644
    mode = stat.S_IMODE(member.mode) or fallback
    return mode & 0o777


IDENTITY_FIELDS = (
    "st_dev",
    "st_ino",
    "st_mode",
    "st_size",
    "st_mtime_ns",
    "st_ctime_ns",
    "st_nlink",
)


def archive_identity(archive_stream: BinaryIO) -> tuple[int, ...]:
    current = os.fstat(archive_stream.fileno())
    if not stat.S_ISREG(current.st_mode) or current.st_nlink != 1 or current.st_size < 1:
        fail("archive must be a non-empty, single-link regular file")
    return tuple(getattr(current, field) for field in IDENTITY_FIELDS)


def verify_sha256(archive_stream: BinaryIO, expected: str) -> tuple[int, ...]:
    archive_stream.seek(0)
    before = os.fstat(archive_stream.fileno())
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size < 1:
        fail("archive must be a non-empty, single-link regular file")
    digest = hashlib.sha256()
    while True:
        block = archive_stream.read(1024 * 1024)
        if not block:
            break
        digest.update(block)
    after = os.fstat(archive_stream.fileno())
    before_identity = tuple(getattr(before, field) for field in IDENTITY_FIELDS)
    if before_identity != tuple(getattr(after, field) for field in IDENTITY_FIELDS):
        fail("archive changed while its SHA-256 was calculated")
    observed = digest.hexdigest()
    if observed != expected.lower():
        fail(f"archive SHA-256 mismatch (observed {observed})")
    return before_identity


def verify_stream_identity(
    archive_stream: BinaryIO,
    expected_identity: tuple[int, ...],
) -> None:
    current = os.fstat(archive_stream.fileno())
    if tuple(getattr(current, field) for field in IDENTITY_FIELDS) != expected_identity:
        fail("archive changed after its descriptor was verified")


def verify_path_identity(archive_path: Path, expected_identity: tuple[int, ...]) -> None:
    current = archive_path.lstat()
    if tuple(getattr(current, field) for field in IDENTITY_FIELDS) != expected_identity:
        fail("archive path no longer identifies the verified descriptor")


def extract_archive(
    archive_stream: BinaryIO,
    destination: Path,
    members: list[tarfile.TarInfo],
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        destination.mkdir(mode=0o700)
    except FileExistsError:
        fail(f"destination already exists: {destination}")

    try:
        archive_stream.seek(0)
        with tarfile.open(fileobj=archive_stream, mode="r:*") as archive:
            by_name = {member.name: member for member in archive.getmembers()}
            ordered = [
                *filter(tarfile.TarInfo.isdir, members),
                *filter(tarfile.TarInfo.isreg, members),
            ]
            for member in ordered:
                current = by_name.get(member.name)
                if current is None or current.type != member.type:
                    fail(f"archive member changed during extraction: {member.name!r}")
                relative = relative_member_path(current.name, label="archive member")
                target = destination.joinpath(*relative.parts)
                if current.isdir():
                    target.mkdir(mode=0o700, parents=True, exist_ok=True)
                    continue

                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                source_stream = archive.extractfile(current)
                if source_stream is None:
                    fail(f"could not read regular archive member: {current.name!r}")
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
                descriptor = os.open(target, flags, 0o600)
                try:
                    with source_stream:
                        with os.fdopen(descriptor, "wb", closefd=False) as output:
                            shutil.copyfileobj(source_stream, output)
                            output.flush()
                            os.fsync(output.fileno())
                    os.fchmod(descriptor, safe_mode(current, directory=False))
                finally:
                    os.close(descriptor)

            for member in members:
                if not (member.issym() or member.islnk()):
                    continue
                current = by_name.get(member.name)
                if current is None or current.type != member.type:
                    fail(f"archive member changed during extraction: {member.name!r}")
                relative = relative_member_path(current.name, label="archive member")
                target = destination.joinpath(*relative.parts)
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                link_target = normalized_link_target(destination, current, relative)
                if current.issym():
                    os.symlink(current.linkname, target)
                else:
                    if not link_target.is_file() or link_target.is_symlink():
                        fail(
                            f"hard-link target is not an extracted regular file: "
                            f"{current.name!r} -> {current.linkname!r}"
                        )
                    os.link(link_target, target, follow_symlinks=False)

            directories = sorted(
                (member for member in members if member.isdir()),
                key=lambda member: len(
                    relative_member_path(member.name, label="archive member").parts
                ),
                reverse=True,
            )
            for member in directories:
                relative = relative_member_path(member.name, label="archive member")
                destination.joinpath(*relative.parts).chmod(safe_mode(member, directory=True))
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("destination", type=Path, nargs="?")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--expected-root", action="append", default=[])
    parser.add_argument("--require-exact-roots", action="store_true")
    parser.add_argument("--expected-sha256", default="")
    parser.add_argument("--containment-root", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    destination: Path | None = None
    extracted = False
    try:
        archive_input = args.archive.expanduser()
        if archive_input.is_symlink():
            fail(f"archive must not be a symbolic link: {archive_input}")
        archive = archive_input.resolve(strict=True)
        if not archive.is_file():
            fail(f"archive must be a regular file: {archive}")
        if args.require_exact_roots and not args.expected_root:
            fail("--require-exact-roots requires at least one --expected-root")
        if args.expected_sha256 and not (
            len(args.expected_sha256) == 64
            and all(character in "0123456789abcdefABCDEF" for character in args.expected_sha256)
        ):
            fail("--expected-sha256 must be exactly 64 hexadecimal characters")

        expected_roots: set[str] = set()
        for value in args.expected_root:
            root = relative_member_path(value, label="expected root")
            if len(root.parts) != 1:
                fail(f"expected root must be one path component: {value!r}")
            expected_roots.add(root.parts[0])

        if args.destination:
            destination_input = args.destination.expanduser()
            if destination_input.is_symlink():
                fail(f"destination must not be a symbolic link: {destination_input}")
            destination = destination_input.resolve(strict=False)
        else:
            destination = Path.cwd().resolve() / ".safe-extract-validation"
        if args.containment_root:
            containment_input = args.containment_root.expanduser()
            if containment_input.is_symlink():
                fail(f"containment root must not be a symbolic link: {containment_input}")
            containment_root = containment_input.resolve(strict=True)
            if not containment_root.is_dir():
                fail(f"containment root must be a non-symlink directory: {containment_root}")
            destination = descendant(
                containment_root,
                destination,
                label="extraction destination",
            )
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(archive, flags)
        with os.fdopen(descriptor, "rb") as archive_stream:
            verified_identity = (
                verify_sha256(archive_stream, args.expected_sha256)
                if args.expected_sha256
                else archive_identity(archive_stream)
            )
            members, roots = inspect_archive(
                archive_stream,
                destination,
                expected_roots,
                args.require_exact_roots,
            )
            verify_stream_identity(archive_stream, verified_identity)
            if not args.validate_only:
                if args.destination is None:
                    fail("destination is required unless --validate-only is used")
                extract_archive(archive_stream, destination, members)
                extracted = True
            verify_stream_identity(archive_stream, verified_identity)
            verify_path_identity(archive, verified_identity)
    except (OSError, tarfile.TarError, UnsafeArchive) as exc:
        if extracted and destination is not None:
            shutil.rmtree(destination, ignore_errors=True)
        print(f"ERROR: unsafe archive: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"OK: validated {len(members)} archive members across {len(roots)} top-level root(s)")


if __name__ == "__main__":
    main()
