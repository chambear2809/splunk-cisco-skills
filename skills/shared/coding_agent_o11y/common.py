#!/usr/bin/env python3
"""Common utilities for coding-agent observability setup skills."""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import stat
import sys
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 is not expected here.
    tomllib = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[3]
# Single source of truth for secret-bearing CLI flags. SECRET_FLAG_RE is built from
# this set so the readable list and the enforcing regex can never drift (SEC-05).
FORBIDDEN_SECRET_FLAGS = (
    "--token",
    "--access-token",
    "--sf-token",
    "--o11y-token",
    "--api-key",
    "--api-token",
    "--galileo-api-key",
    "--galileo-token",
    "--client-secret",
    "--authorization",
    "--bearer-token",
    "--password",
)
SECRET_FLAG_RE = re.compile(
    r"^(?:" + "|".join(re.escape(flag) for flag in FORBIDDEN_SECRET_FLAGS) + r")(?:=|$)",
    re.IGNORECASE,
)
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(?:token|password|api[_-]?key|secret|access[_-]?token)\s*="
)
# Colon- or equals-delimited secret key followed by a value, for scanning rendered
# YAML/JSON config (SEC-01). Matches header/key names like X-SF-TOKEN and
# Galileo-API-Key in addition to bare token/secret/api-key assignments.
SECRET_KEYVAL_RE = re.compile(
    r"(?i)(?:token|password|api[_-]?key|secret|access[_-]?token|authorization"
    r"|galileo-api-key|x-[a-z0-9-]*(?:api|auth|key|token)[a-z0-9-]*)"
    r"[\"']?\s*[:=]\s*(?P<value>.+)$"
)
UNSAFE_LONG_VALUE_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9_+./=-]{28,}(?![A-Za-z0-9])")
ENV_PLACEHOLDER_RE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*\}$")
SAFE_LITERAL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:/@=-]{0,180}$")
SECRET_HEADER_NAME_RE = re.compile(
    r"(?i)^(authorization|proxy-authorization|x-.*(?:api|auth|key|token).*)$"
)


class UsageError(ValueError):
    """A CLI or spec error that should be displayed without a traceback."""


def reject_secret_argv(argv: list[str]) -> None:
    for arg in argv:
        if SECRET_FLAG_RE.match(arg):
            flag = arg.split("=", 1)[0]
            raise UsageError(
                f"{flag} would expose a secret on the command line; use a file-based "
                "secret handoff or an environment placeholder such as ${SPLUNK_ACCESS_TOKEN}."
            )


def repo_rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def absolute_path_no_follow(path: Path) -> Path:
    """Return an absolute lexical path without resolving symlink components."""
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def _open_safe_output_directory(path: Path) -> int:
    """Open/create a directory tree without following symlink components."""
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise UsageError("platform lacks O_NOFOLLOW/O_DIRECTORY; cannot write outputs safely")

    absolute = Path(os.path.abspath(os.fspath(path)))
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(absolute.anchor or os.sep, flags)
    try:
        for component in absolute.parts[1:]:
            if component in {"", "."}:
                continue
            try:
                child = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                try:
                    os.mkdir(component, mode=0o755, dir_fd=descriptor)
                except FileExistsError:
                    # Another writer won the create race. The no-follow open
                    # below still requires the winner to be a real directory.
                    pass
                child = os.open(component, flags, dir_fd=descriptor)
            metadata = os.fstat(child)
            if not stat.S_ISDIR(metadata.st_mode):
                os.close(child)
                raise UsageError(f"output directory component is not a directory: {path}")
            os.close(descriptor)
            descriptor = child
        return descriptor
    except OSError as exc:
        os.close(descriptor)
        raise UsageError(
            f"output directory must not contain symlinks or non-directories: {path}"
        ) from exc
    except Exception:
        os.close(descriptor)
        raise


def _output_target_metadata(directory_fd: int, name: str, path: Path) -> os.stat_result | None:
    try:
        metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise UsageError(
            f"output target must be a single-hardlink regular file, not a symlink or special file: {path}"
        )
    return metadata


def _output_fingerprint(metadata: os.stat_result | None) -> tuple[int, ...] | None:
    if metadata is None:
        return None
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _atomic_write_bytes(
    path: Path,
    content: bytes,
    *,
    executable: bool = False,
    mode: int | None = None,
) -> None:
    """Atomically write bytes without following path or target symlinks."""
    path = Path(path)
    if path.name in {"", ".", ".."}:
        raise UsageError(f"output target must name a file: {path}")
    if mode is not None and (mode < 0 or mode > 0o7777):
        raise UsageError(f"invalid output mode for {path}: {mode:o}")

    directory_fd: int | None = None
    temporary_fd: int | None = None
    temporary_name: str | None = None
    try:
        directory_fd = _open_safe_output_directory(path.parent)
        initial = _output_target_metadata(directory_fd, path.name, path)
        if mode is not None:
            final_mode = mode
        elif initial is None:
            final_mode = 0o755 if executable else 0o644
        else:
            final_mode = stat.S_IMODE(initial.st_mode)
            if executable:
                final_mode |= stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH

        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0)
        )
        for _ in range(128):
            candidate = f".{path.name}.{secrets.token_hex(12)}.tmp"
            try:
                temporary_fd = os.open(candidate, flags, 0o600, dir_fd=directory_fd)
                temporary_name = candidate
                break
            except FileExistsError:
                continue
        if temporary_fd is None or temporary_name is None:
            raise UsageError(f"could not allocate a private temporary output for: {path}")

        payload = content
        offset = 0
        while offset < len(payload):
            written = os.write(temporary_fd, payload[offset:])
            if written <= 0:
                raise OSError("short write while creating rendered output")
            offset += written
        os.fchmod(temporary_fd, final_mode)
        os.fsync(temporary_fd)
        os.close(temporary_fd)
        temporary_fd = None

        current = _output_target_metadata(directory_fd, path.name, path)
        if _output_fingerprint(current) != _output_fingerprint(initial):
            raise UsageError(f"output target changed while it was being rendered: {path}")

        os.replace(
            temporary_name,
            path.name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        temporary_name = None
        final = _output_target_metadata(directory_fd, path.name, path)
        if final is None or stat.S_IMODE(final.st_mode) != final_mode:
            raise UsageError(f"output target failed final validation: {path}")
        os.fsync(directory_fd)
    except UsageError:
        raise
    except OSError as exc:
        raise UsageError(f"could not safely write output target {path}: {exc}") from exc
    finally:
        if temporary_fd is not None:
            os.close(temporary_fd)
        if temporary_name is not None and directory_fd is not None:
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        if directory_fd is not None:
            os.close(directory_fd)


def write_text(
    path: Path,
    content: str,
    executable: bool = False,
    *,
    mode: int | None = None,
) -> None:
    """Atomically write text without following path or target symlinks."""
    _atomic_write_bytes(
        path,
        content.encode("utf-8"),
        executable=executable,
        mode=mode,
    )


def write_json(path: Path, payload: Any, executable: bool = False) -> None:
    write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n", executable=executable)


def read_bytes_safe(path: Path) -> tuple[bytes, int]:
    """Read a single-link regular file through no-follow descriptors."""
    path = Path(path)
    if path.name in {"", ".", ".."}:
        raise UsageError(f"input source must name a file: {path}")

    directory_fd: int | None = None
    source_fd: int | None = None
    try:
        directory_fd = _open_safe_output_directory(path.parent)
        initial = _output_target_metadata(directory_fd, path.name, path)
        if initial is None:
            raise UsageError(f"input source does not exist: {path}")
        flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        source_fd = os.open(path.name, flags, dir_fd=directory_fd)
        opened = os.fstat(source_fd)
        if _output_fingerprint(opened) != _output_fingerprint(initial):
            raise UsageError(f"input source changed while it was being opened: {path}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(source_fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        final = os.fstat(source_fd)
        if _output_fingerprint(final) != _output_fingerprint(opened):
            raise UsageError(f"input source changed while it was being read: {path}")
        return b"".join(chunks), stat.S_IMODE(opened.st_mode)
    except UsageError:
        raise
    except OSError as exc:
        raise UsageError(f"could not safely read input source {path}: {exc}") from exc
    finally:
        if source_fd is not None:
            os.close(source_fd)
        if directory_fd is not None:
            os.close(directory_fd)


def copy_file_safe(source: Path, target: Path, *, mode: int | None = None) -> None:
    """Atomically copy a regular file without following source or target links."""
    payload, source_mode = read_bytes_safe(source)
    _atomic_write_bytes(target, payload, mode=source_mode if mode is None else mode)


def reset_output_subdirectories(output_dir: Path, children: tuple[str, ...]) -> None:
    """Remove renderer-owned child directories without following symlinks."""
    if not getattr(shutil.rmtree, "avoids_symlink_attacks", False):
        raise UsageError("platform lacks symlink-safe shutil.rmtree support")

    directory_fd: int | None = None
    try:
        directory_fd = _open_safe_output_directory(output_dir)
        for child in children:
            if Path(child).name != child or child in {"", ".", ".."}:
                raise UsageError(f"unsafe renderer-owned output name: {child}")
            try:
                metadata = os.stat(child, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            if not stat.S_ISDIR(metadata.st_mode):
                raise UsageError(
                    f"renderer-owned output must be a real directory, not a symlink or special file: "
                    f"{output_dir / child}"
                )
            try:
                shutil.rmtree(child, dir_fd=directory_fd)
            except OSError as exc:
                raise UsageError(
                    f"could not safely remove renderer-owned output: {output_dir / child}"
                ) from exc
        os.fsync(directory_fd)
    finally:
        if directory_fd is not None:
            os.close(directory_fd)


def load_structured_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise UsageError(f"spec file does not exist: {path}")
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix == ".json" or text.lstrip().startswith("{"):
        data = json.loads(text)
    elif suffix == ".toml":
        if tomllib is None:
            raise UsageError("TOML specs require Python 3.11+ tomllib")
        data = tomllib.loads(text)
    else:
        raise UsageError("spec files must be JSON or TOML")
    if not isinstance(data, dict):
        raise UsageError("spec root must be an object")
    return data


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)  # type: ignore[arg-type]
        else:
            result[key] = value
    return result


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def shell_join(argv: list[str]) -> str:
    import shlex

    return " ".join(shlex.quote(item) for item in argv)


def ensure_safe_external_value(label: str, value: str, *, reject_token_like: bool = False) -> None:
    if not value:
        return
    if ENV_PLACEHOLDER_RE.fullmatch(value):
        return
    if SECRET_ASSIGNMENT_RE.search(value):
        raise UsageError(f"{label} looks like an inline secret assignment; use an environment placeholder.")
    if reject_token_like and UNSAFE_LONG_VALUE_RE.search(value):
        raise UsageError(f"{label} looks like raw secret material; use an environment placeholder.")
    if UNSAFE_LONG_VALUE_RE.search(value) and not SAFE_LITERAL_RE.fullmatch(value):
        raise UsageError(f"{label} looks like raw secret material; use an environment placeholder.")
    if not SAFE_LITERAL_RE.fullmatch(value):
        raise UsageError(f"{label} must be a safe literal or an environment placeholder.")


def ensure_safe_external_header(key: str, value: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", key):
        raise UsageError("external header keys must contain only letters, digits, underscore, dot, or hyphen")
    ensure_safe_external_value(f"header {key}", value, reject_token_like=True)
    if SECRET_HEADER_NAME_RE.fullmatch(key) and not ENV_PLACEHOLDER_RE.fullmatch(value):
        raise UsageError(f"header {key} may carry credentials; use an environment placeholder.")


def parse_header(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise UsageError("--external-header must use KEY=VALUE")
    key, header_value = value.split("=", 1)
    key = key.strip()
    header_value = header_value.strip()
    ensure_safe_external_header(key, header_value)
    return key, header_value


def validate_toml_file(path: Path) -> None:
    if tomllib is None:
        raise UsageError("TOML validation requires Python 3.11+ tomllib")
    with path.open("rb") as handle:
        tomllib.load(handle)


# Any ${NAME} or ${env:NAME} placeholder reference (allowed in rendered files).
_PLACEHOLDER_ANY_RE = re.compile(r"\$\{(?:env:)?[A-Za-z_][A-Za-z0-9_]*\}")


def _residual_value_is_secret(value: str) -> bool:
    """True when a key's value, after removing placeholder references, still holds
    real secret-looking material (a long high-entropy literal). Empty/placeholder-only
    residuals are safe."""
    residual = _PLACEHOLDER_ANY_RE.sub("", value)
    # Strip surrounding quotes/whitespace/commas left after placeholder removal.
    residual = residual.strip().strip('"\'').strip().rstrip(",").strip().strip('"\'')
    if not residual:
        return False
    return bool(UNSAFE_LONG_VALUE_RE.search(residual))


def scan_rendered_for_secret_leaks(root: Path) -> list[str]:
    errors: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        # Test markers: flag regardless of form.
        stripped = _PLACEHOLDER_ANY_RE.sub("", text)
        if "SUPER_SECRET" in stripped or "SHOULD_NOT_RENDER" in stripped:
            errors.append(f"{rel}: contains test secret marker")
            continue

        # Per-line scan. A line is only flagged when, after removing every allowed
        # ${...}/${env:...} placeholder, a secret-like key still carries a real
        # literal value. This catches both `KEY=<literal>` and `Key: "<literal>"`
        # (YAML/JSON) forms and closes the assignment-form evasion where a header
        # name substring on the line previously suppressed the check.
        flagged = False
        for raw_line in text.splitlines():
            match = SECRET_KEYVAL_RE.search(raw_line)
            if match and _residual_value_is_secret(match.group("value")):
                errors.append(f"{rel}: contains secret-like assignment")
                flagged = True
                break
        if flagged:
            continue
    return errors


def print_payload(payload: Any, json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    if isinstance(payload, dict) and "message" in payload:
        print(str(payload["message"]))
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))


def command_failed(exc: Exception, json_output: bool) -> int:
    payload = {"ok": False, "errors": [str(exc)]}
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"ERROR: {exc}", file=sys.stderr)
    return 2 if isinstance(exc, UsageError) else 1


def getenv_path(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value else default
