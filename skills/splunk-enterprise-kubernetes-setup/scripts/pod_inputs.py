#!/usr/bin/env python3
"""Verify and privately stage hash-reviewed Splunk POD external inputs."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
from pathlib import Path


class InputError(ValueError):
    """A bundle or external POD input does not match the reviewed contract."""


def load_verifier():
    source = Path(__file__).with_name("bundle_verify.py")
    if not source.is_file():
        source = Path(__file__).with_name("bundle-verify.py")
    spec = importlib.util.spec_from_file_location("splunk_pod_bundle_verify", source)
    if spec is None or spec.loader is None:
        raise InputError("hardened bundle verifier is unavailable")
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def load_bundle(root: Path) -> tuple[dict, dict]:
    verifier = load_verifier()
    try:
        manifest = verifier.load_manifest(root, "pod")
        metadata = verifier.read_json_nofollow(root.resolve() / "metadata.json")
    except verifier.VerifyError as error:
        raise InputError(str(error)) from error
    return manifest, metadata


def copy_reviewed(
    source: Path, destination: Path, expected: str, *, require_private: bool = False
) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise InputError(f"invalid external digest for {source}")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        source_fd = os.open(source, flags)
    except OSError as error:
        raise InputError(f"cannot open reviewed external input {source}: {error}") from error
    try:
        before = os.fstat(source_fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise InputError(f"external input must be a singly linked regular file: {source}")
        if require_private and (
            stat.S_IMODE(before.st_mode) & 0o077 or before.st_uid != os.geteuid()
        ):
            raise InputError(
                f"private input must be owner-controlled with no group/other access: {source}"
            )
        output_fd = os.open(
            destination,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o400,
        )
        digest = hashlib.sha256()
        try:
            while True:
                chunk = os.read(source_fd, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                view = memoryview(chunk)
                while view:
                    written = os.write(output_fd, view)
                    if written <= 0:
                        raise OSError("short write while staging external input")
                    view = view[written:]
            os.fsync(output_fd)
        finally:
            os.close(output_fd)
        after = os.fstat(source_fd)
        before_identity = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        after_identity = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if before_identity != after_identity:
            raise InputError(f"external input changed while being staged: {source}")
        if digest.hexdigest() != expected:
            raise InputError(f"external input digest drifted: {source}")
        destination.chmod(0o400)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    finally:
        os.close(source_fd)


def write_private(path: Path, content: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        data = content.encode("utf-8")
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short write while creating staged POD input")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def replace_values(value: object, replacements: dict[str, str]) -> object:
    if isinstance(value, str):
        return replacements.get(value, value)
    if isinstance(value, list):
        return [replace_values(child, replacements) for child in value]
    if isinstance(value, dict):
        return {
            key: replace_values(child, replacements)
            for key, child in value.items()
            if key != "external_input_paths"
        }
    return value


def stage(root: Path, output: Path) -> None:
    manifest, metadata = load_bundle(root)
    output_mode = stat.S_IMODE(output.lstat().st_mode) if output.exists() else None
    if output.is_symlink() or not output.is_dir() or output_mode != 0o700:
        raise InputError("staging directory must be a real mode-0700 directory")
    external = manifest["external_files"]
    path_map = metadata.get("external_input_paths")
    if not isinstance(path_map, dict):
        raise InputError("POD metadata has no canonical external-input map")
    canonical_to_staged: dict[str, str] = {}
    private_inputs = {
        path_map.get(metadata.get("ssh_private_key_file", "")),
        path_map.get(metadata.get("ingress_private_key_file", "")),
    }
    private_inputs.discard(None)
    for index, (canonical, expected) in enumerate(sorted(external.items())):
        source = Path(canonical)
        if not source.is_absolute():
            raise InputError(f"external manifest path is not absolute: {canonical}")
        suffix = "".join(source.suffixes)[-48:]
        destination = output / f"input-{index:04d}{suffix}"
        copy_reviewed(
            source,
            destination,
            expected,
            require_private=canonical in private_inputs,
        )
        canonical_to_staged[canonical] = str(destination.resolve())
    raw_to_staged: dict[str, str] = {}
    for raw, canonical in path_map.items():
        if not isinstance(raw, str) or not isinstance(canonical, str):
            raise InputError("external-input map must contain string paths")
        if canonical in canonical_to_staged:
            raw_to_staged[raw] = canonical_to_staged[canonical]
    missing = sorted(set(external) - set(path_map.values()))
    if missing:
        raise InputError(f"external inputs are absent from metadata: {missing}")

    config = (root / "cluster-config.yaml").read_text(encoding="utf-8")
    for raw, staged in sorted(raw_to_staged.items(), key=lambda item: -len(item[0])):
        config = config.replace(json.dumps(raw), json.dumps(staged))
    for raw in raw_to_staged:
        if json.dumps(raw) in config:
            raise InputError(f"external path was not fully staged in config: {raw}")
    staged_metadata = replace_values(metadata, raw_to_staged)
    write_private(output / "cluster-config.yaml", config)
    write_private(
        output / "metadata.json",
        json.dumps(staged_metadata, indent=2, sort_keys=True) + "\n",
    )
    write_private(
        output / "path-map.json",
        json.dumps({"raw_to_staged": raw_to_staged}, indent=2, sort_keys=True) + "\n",
    )


def restore(config_path: Path, map_path: Path) -> None:
    mapping = json.loads(map_path.read_text(encoding="utf-8")).get("raw_to_staged")
    if not isinstance(mapping, dict):
        raise InputError("staged path map is invalid")
    config = config_path.read_text(encoding="utf-8")
    for raw, staged in sorted(mapping.items(), key=lambda item: -len(item[1])):
        config = config.replace(json.dumps(staged), json.dumps(raw))
    if any(json.dumps(staged) in config for staged in mapping.values()):
        raise InputError("staged path remains in installer-updated configuration")
    temporary = config_path.with_name(config_path.name + ".restored")
    write_private(temporary, config)
    os.replace(temporary, config_path)


def main() -> int:
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "verify":
            load_bundle(Path(sys.argv[2]))
        elif len(sys.argv) == 4 and sys.argv[1] == "stage":
            stage(Path(sys.argv[2]), Path(sys.argv[3]))
        elif len(sys.argv) == 4 and sys.argv[1] == "restore":
            restore(Path(sys.argv[2]), Path(sys.argv[3]))
        else:
            raise InputError(
                "usage: pod-inputs.py verify BUNDLE | stage BUNDLE OUTPUT | "
                "restore CONFIG PATH_MAP"
            )
    except (InputError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
