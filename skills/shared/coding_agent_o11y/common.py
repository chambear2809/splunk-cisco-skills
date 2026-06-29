#!/usr/bin/env python3
"""Common utilities for coding-agent observability setup skills."""

from __future__ import annotations

import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 is not expected here.
    tomllib = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[3]
FORBIDDEN_SECRET_FLAGS = {
    "--token",
    "--access-token",
    "--sf-token",
    "--o11y-token",
    "--api-key",
    "--password",
}
SECRET_FLAG_RE = re.compile(
    r"^--(?:token|access-token|sf-token|o11y-token|api-key|password)(?:=|$)",
    re.IGNORECASE,
)
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(?:token|password|api[_-]?key|secret|access[_-]?token)\s*="
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


def write_text(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def write_json(path: Path, payload: Any, executable: bool = False) -> None:
    write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n", executable=executable)


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


def scan_rendered_for_secret_leaks(root: Path) -> list[str]:
    allowed_placeholders = {
        "${SPLUNK_ACCESS_TOKEN}",
        "${SPLUNK_O11Y_TOKEN}",
        "${OTLP_TOKEN}",
        "${CODEX_O11Y_TOKEN}",
    }
    errors: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        searchable = text
        for placeholder in allowed_placeholders:
            searchable = searchable.replace(placeholder, "")
        if "SUPER_SECRET" in searchable or "SHOULD_NOT_RENDER" in searchable:
            errors.append(f"{rel}: contains test secret marker")
        if SECRET_ASSIGNMENT_RE.search(searchable):
            # Keep config keys and placeholders out of the generic warning noise.
            for line in searchable.splitlines():
                if SECRET_ASSIGNMENT_RE.search(line) and "${" not in line and "X-SF-TOKEN" not in line:
                    errors.append(f"{rel}: contains secret-like assignment")
                    break
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
