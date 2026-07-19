#!/usr/bin/env python3
"""Report value-free structural YAML changes for a staged collector config."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any


MAX_CONFIG_BYTES = 8 * 1024 * 1024
MAX_CHANGES = 10_000


def read_yaml(path: Path) -> tuple[bytes, dict[str, Any]]:
    try:
        info = path.lstat()
    except OSError as exc:
        raise ValueError(f"cannot inspect config: {path}") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError(f"config must be a single-link regular file: {path}")
    if not 1 <= info.st_size <= MAX_CONFIG_BYTES:
        raise ValueError(f"config size is outside the allowed range: {path}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        data = os.read(descriptor, MAX_CONFIG_BYTES + 1)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        len(data) != info.st_size
        or len(data) > MAX_CONFIG_BYTES
        or (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    ):
        raise ValueError(f"config changed or could not be read completely: {path}")
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise ValueError("PyYAML is required; install requirements-dev.txt") from exc
    try:
        document = yaml.safe_load(data)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid collector YAML: {path}") from exc
    if not isinstance(document, dict):
        raise ValueError(f"collector config root must be a mapping: {path}")
    return data, document


def pointer(parent: str, key: object) -> str:
    escaped = str(key).replace("~", "~0").replace("/", "~1")
    return f"{parent}/{escaped}"


def compare(
    before: Any,
    after: Any,
    path: str,
    added: list[str],
    removed: list[str],
    changed: list[str],
) -> None:
    if len(added) + len(removed) + len(changed) > MAX_CHANGES:
        raise ValueError("semantic diff exceeds the change limit")
    if type(before) is not type(after):
        changed.append(path or "/")
        return
    if isinstance(before, dict):
        before_keys = set(before)
        after_keys = set(after)
        added.extend(
            pointer(path, key) for key in sorted(after_keys - before_keys, key=str)
        )
        removed.extend(
            pointer(path, key) for key in sorted(before_keys - after_keys, key=str)
        )
        if len(added) + len(removed) + len(changed) > MAX_CHANGES:
            raise ValueError("semantic diff exceeds the change limit")
        for key in sorted(before_keys & after_keys, key=str):
            compare(
                before[key], after[key], pointer(path, key), added, removed, changed
            )
        return
    if isinstance(before, list):
        if before != after:
            changed.append(path or "/")
        return
    if before != after:
        changed.append(path or "/")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    args = parser.parse_args()
    try:
        before_bytes, before = read_yaml(args.before)
        after_bytes, after = read_yaml(args.after)
        added: list[str] = []
        removed: list[str] = []
        changed: list[str] = []
        compare(before, after, "", added, removed, changed)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
    result = {
        "before_sha256": hashlib.sha256(before_bytes).hexdigest(),
        "after_sha256": hashlib.sha256(after_bytes).hexdigest(),
        "added": sorted(added),
        "removed": sorted(removed),
        "changed": sorted(changed),
        "counts": {
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
        },
    }
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
